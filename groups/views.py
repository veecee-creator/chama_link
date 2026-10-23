
import csv
import json
import logging
import os
import re
import calendar
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.contrib.staticfiles import finders
from django.core.exceptions import PermissionDenied
from django.core import signing
from django.db import transaction as db_transaction
from django.db.models import Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.urls import reverse
from urllib.parse import urlencode
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.forms import ProfileForm, ProfilePictureForm
from accounts.models import UserProfile

from .models import (
    Chama,
    Membership,
    Contribution,
    Loan,
    LoanRepayment,
    FinancialActivity,
    MpesaTransaction,
    ChamaCashflowEntry,
    MemberFine,
    FinePayment,
    RotationPayout,
    SavingsGoal,
    GoalProgressEntry,
    ChamaMeeting,
    MeetingAttendance,
    PlanInquiry,
)

from .forms import (
    MembershipForm,
    ChamaForm,
    ContributionForm,
    LoanForm,
    LoanRepaymentForm,
    ChamaCashflowEntryForm,
    MemberFineForm,
    FinePaymentForm,
    SavingsGoalForm,
    GoalProgressForm,
    ChamaMeetingForm,
    MeetingMinutesForm,
    MeetingAttendanceForm,
    PlanInquiryForm,
    normalize_national_id,
)

from .mpesa import initiate_stk_push


logger = logging.getLogger(__name__)

OFFICIAL_ROLES = {'CHAIRPERSON', 'TREASURER', 'SECRETARY'}


def log_financial_activity(actor, chama, action, description, record=None):
    FinancialActivity.objects.create(
        actor=actor if getattr(actor, 'is_authenticated', False) else None,
        chama=chama,
        action=action,
        description=description[:255],
        record_type=record.__class__.__name__ if record else '',
        record_id=record.pk if record else None,
    )


def add_months(day, months):
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    return day.replace(year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1]))


def service_worker(request):
    worker_path = finders.find('groups/service-worker.js')
    if not worker_path:
        return HttpResponse('Service worker unavailable', status=404)
    response = HttpResponse(
        Path(worker_path).read_text(encoding='utf-8'),
        content_type='application/javascript; charset=utf-8',
    )
    response['Service-Worker-Allowed'] = '/'
    response['Cache-Control'] = 'no-cache'
    return response


def get_contribution_cycle(membership):
    """Return the next contribution target while preserving unpaid arrears."""
    chama = membership.chama
    today = timezone.localdate()
    due_day = chama.contribution_due_day
    joined_on = timezone.localtime(membership.joined_at).date()

    if chama.contribution_frequency == 'WEEKLY':
        first_due = joined_on - timedelta(days=joined_on.weekday()) + timedelta(days=due_day - 1)
        if first_due < joined_on:
            first_due += timedelta(days=7)
        if first_due <= today:
            due_count = (today - first_due).days // 7 + 1
        else:
            due_count = 0
        due_date = today - timedelta(days=today.weekday()) + timedelta(days=due_day - 1)
        is_due_today = due_date == today
        if due_date < today:
            due_date += timedelta(days=7)
    else:
        first_due = joined_on.replace(day=min(due_day, calendar.monthrange(joined_on.year, joined_on.month)[1]))
        if first_due < joined_on:
            first_due = add_months(first_due, 1)
        if first_due <= today:
            months_elapsed = (today.year - first_due.year) * 12 + today.month - first_due.month
            latest_due = add_months(first_due, months_elapsed)
            due_count = months_elapsed + (1 if latest_due <= today else 0)
        else:
            due_count = 0
        due_date = today.replace(day=min(due_day, calendar.monthrange(today.year, today.month)[1]))
        is_due_today = due_date == today
        if due_date < today:
            due_date = add_months(due_date, 1)

    paid = Contribution.objects.filter(
        membership=membership
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    overdue_target = chama.contribution_amount * due_count
    projected_target = overdue_target + chama.contribution_amount
    remaining = max(projected_target - paid, Decimal('0.00'))
    if remaining == 0:
        status = 'CLEARED'
    elif paid < overdue_target:
        status = 'OVERDUE'
    elif is_due_today:
        status = 'DUE_TODAY'
    else:
        status = 'UPCOMING'
    status_label = {
        'CLEARED': 'Paid',
        'OVERDUE': 'Overdue',
        'DUE_TODAY': 'Due today',
        'UPCOMING': 'Upcoming',
    }[status]
    return {
        'amount': chama.contribution_amount,
        'paid': paid,
        'remaining': remaining,
        'due_date': due_date,
        'frequency': chama.get_contribution_frequency_display(),
        'status': status,
        'status_label': status_label,
    }


# =========================
# PERMISSION HELPERS
# =========================

def get_user_membership(user, chama_id=None):
    """Return this user's membership in the selected chama."""
    memberships = Membership.objects.filter(user=user).select_related('chama')
    if chama_id:
        return memberships.filter(chama_id=chama_id).first()
    return memberships.order_by('joined_at').first()


def is_demo_tester(user):
    """Allow the configured demo login to exercise every chama role."""
    return (
        getattr(user, 'is_authenticated', False)
        and os.getenv('CHAMALINK_DEMO_MODE', '').lower() == 'true'
        and bool(os.getenv('DEMO_USERNAME'))
        and user.get_username() == os.getenv('DEMO_USERNAME')
    )


def is_chama_role(user, chama, *roles):
    if user.is_superuser or is_demo_tester(user):
        return True
    return Membership.objects.filter(
        user=user, chama=chama, role__in=roles
    ).exists()


def is_chama_official(user, chama):
    """Check whether a user is an official of a particular chama."""
    if user.is_superuser or is_demo_tester(user):
        return True

    return Membership.objects.filter(
        user=user,
        chama=chama,
        role__in=OFFICIAL_ROLES,
    ).exists()


def landing(request):
    return render(request, 'groups/landing.html')


def selected_chama_for_user(request):
    membership = get_user_membership(
        request.user, request.session.get('active_chama_id')
    )
    if membership:
        return membership.chama, membership
    if request.user.is_superuser:
        chama = Chama.objects.order_by('name').first()
        if chama:
            return chama, None
    return None, None


def plans(request):
    if request.method == 'POST' and not request.user.is_authenticated:
        return redirect('login')
    chama, membership = (
        selected_chama_for_user(request)
        if request.user.is_authenticated else (None, None)
    )
    can_request = bool(
        membership and is_chama_role(
            request.user, membership.chama, 'CHAIRPERSON', 'TREASURER'
        )
    )
    form = PlanInquiryForm()
    if request.method == 'POST':
        if not can_request:
            raise PermissionDenied('Only a chairperson or treasurer can request a group plan.')
        form = PlanInquiryForm(request.POST)
        if form.is_valid():
            inquiry = form.save(commit=False)
            inquiry.chama = membership.chama
            inquiry.requested_by = request.user
            inquiry.save()
            if settings.CHAMALINK_SALES_EMAIL:
                send_mail(
                    subject=f'New ChamaLink Plus inquiry: {membership.chama.name}',
                    message=(
                        f'Group: {membership.chama.name}\n'
                        f'Contact: {inquiry.contact_phone}\n'
                        f'Email: {inquiry.contact_email or "Not provided"}\n\n'
                        f'{inquiry.message or "No additional message."}'
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[settings.CHAMALINK_SALES_EMAIL],
                    fail_silently=True,
                )
            messages.success(
                request,
                'Your ChamaLink Plus request is saved. Our team will follow up using the contact details you provided.',
            )
            return redirect('plans')

    inquiries = PlanInquiry.objects.none()
    if can_request:
        inquiries = PlanInquiry.objects.filter(
            chama=membership.chama, requested_by=request.user
        )[:5]
    return render(request, 'groups/plans.html', {
        'chama': chama,
        'membership': membership,
        'form': form,
        'can_request': can_request,
        'inquiries': inquiries,
        'has_premium_access': bool(chama and chama.has_premium_access),
    })


@login_required
def savings_goals(request):
    chama, membership = selected_chama_for_user(request)
    if chama is None:
        messages.info(request, 'Create or join a chama before setting group savings goals.')
        return redirect('dashboard')
    has_premium_access = chama.has_premium_access
    can_manage = has_premium_access and is_chama_role(
        request.user, chama, 'CHAIRPERSON', 'TREASURER'
    )

    goal_form = SavingsGoalForm()
    progress_form = GoalProgressForm()
    if request.method == 'POST':
        if not has_premium_access:
            messages.info(request, 'ChamaLink Plus includes group goal tracking.')
            return redirect('plans')
        if not can_manage:
            raise PermissionDenied('Only the chairperson or treasurer can update group goals.')
        action = request.POST.get('action')
        if action == 'create_goal':
            goal_form = SavingsGoalForm(request.POST)
            if goal_form.is_valid():
                goal = goal_form.save(commit=False)
                goal.chama = chama
                goal.created_by = request.user
                goal.save()
                messages.success(request, f'“{goal.title}” has been added to your group goals.')
                return redirect('savings_goals')
        elif action == 'record_progress':
            goal = get_object_or_404(SavingsGoal, pk=request.POST.get('goal_id'), chama=chama)
            progress_form = GoalProgressForm(request.POST)
            if progress_form.is_valid():
                entry = progress_form.save(commit=False)
                entry.goal = goal
                entry.recorded_by = request.user
                entry.save()
                messages.success(request, 'Goal progress updated. This planning tracker does not post a contribution or move money.')
                return redirect('savings_goals')
            goal_form = SavingsGoalForm()
        else:
            raise PermissionDenied('Unknown goal action.')

    goals = SavingsGoal.objects.filter(chama=chama).prefetch_related(
        'progress_entries__recorded_by'
    )
    return render(request, 'groups/savings_goals.html', {
        'chama': chama,
        'membership': membership,
        'goals': goals,
        'goal_form': goal_form,
        'progress_form': progress_form,
        'can_manage': can_manage,
        'has_premium_access': has_premium_access,
    })


@login_required
def meetings(request):
    chama, membership = selected_chama_for_user(request)
    if chama is None:
        messages.info(request, 'Create or join a chama before planning meetings.')
        return redirect('dashboard')
    has_premium_access = chama.has_premium_access
    can_manage = has_premium_access and is_chama_role(
        request.user, chama, 'CHAIRPERSON', 'SECRETARY'
    )

    meeting_form = ChamaMeetingForm()
    attendance_form = MeetingAttendanceForm()
    attendance_form.fields['membership'].queryset = Membership.objects.filter(
        chama=chama, is_active=True
    ).order_by('full_name')

    if request.method == 'POST':
        if not has_premium_access:
            messages.info(request, 'Meeting planning and attendance are included in ChamaLink Plus.')
            return redirect('plans')
        if not can_manage:
            raise PermissionDenied('Only the chairperson or secretary can manage meeting records.')
        action = request.POST.get('action')
        if action == 'create_meeting':
            meeting_form = ChamaMeetingForm(request.POST)
            if meeting_form.is_valid():
                meeting = meeting_form.save(commit=False)
                meeting.chama = chama
                meeting.created_by = request.user
                meeting.save()
                messages.success(request, 'Meeting added to the group calendar.')
                return redirect('meetings')
        elif action == 'save_minutes':
            meeting = get_object_or_404(ChamaMeeting, pk=request.POST.get('meeting_id'), chama=chama)
            minutes_form = MeetingMinutesForm(request.POST, instance=meeting)
            if minutes_form.is_valid():
                minutes_form.save()
                messages.success(request, 'Meeting notes saved.')
                return redirect('meetings')
        elif action == 'record_attendance':
            meeting = get_object_or_404(ChamaMeeting, pk=request.POST.get('meeting_id'), chama=chama)
            attendance_form = MeetingAttendanceForm(request.POST)
            attendance_form.fields['membership'].queryset = Membership.objects.filter(
                chama=chama, is_active=True
            )
            if attendance_form.is_valid():
                attendance = attendance_form.save(commit=False)
                attendance.meeting = meeting
                attendance.recorded_by = request.user
                MeetingAttendance.objects.update_or_create(
                    meeting=meeting,
                    membership=attendance.membership,
                    defaults={'status': attendance.status, 'recorded_by': request.user},
                )
                messages.success(request, 'Attendance saved.')
                return redirect('meetings')
        else:
            raise PermissionDenied('Unknown meeting action.')

    meeting_list = ChamaMeeting.objects.filter(chama=chama).prefetch_related(
        'attendance__membership'
    )
    return render(request, 'groups/meetings.html', {
        'chama': chama,
        'membership': membership,
        'meetings': meeting_list,
        'meeting_form': meeting_form,
        'attendance_form': attendance_form,
        'minutes_form': MeetingMinutesForm(),
        'can_manage': can_manage,
        'has_premium_access': has_premium_access,
    })


@login_required
def chama_directory(request):
    query = request.GET.get('q', '').strip()
    chamas = Chama.objects.all().order_by('name')
    if query:
        chamas = chamas.filter(name__icontains=query)
    linked_ids = Membership.objects.filter(
        user=request.user
    ).values_list('chama_id', flat=True)
    return render(request, 'groups/chama_directory.html', {
        'chamas': chamas,
        'query': query,
        'linked_ids': set(linked_ids),
    })


@login_required
def join_chama(request, chama_id):
    chama = get_object_or_404(Chama, pk=chama_id)
    invite_token = request.GET.get('invite') or request.POST.get('invite')
    invited_membership = None
    if invite_token:
        try:
            invite_data = signing.loads(
                invite_token, salt='chama-member-invite', max_age=7 * 24 * 60 * 60
            )
            invited_membership = Membership.objects.get(
                pk=invite_data['membership_id'], chama=chama,
                is_active=True, user__isnull=True,
            )
        except (signing.BadSignature, signing.SignatureExpired, Membership.DoesNotExist, KeyError, TypeError, ValueError):
            messages.error(request, 'This invitation is invalid, expired, or already used. Ask your chairperson for a new link.')
            invite_token = None

    if request.method == 'POST':
        if invite_token and invited_membership:
            if Membership.objects.filter(user=request.user, chama=chama).exists():
                messages.error(request, 'Your account is already linked to a member record in this chama.')
                return redirect('join_chama', chama_id=chama.pk)
            invited_membership.user = request.user
            invited_membership.save(update_fields=['user'])
            request.session['active_chama_id'] = chama.pk
            messages.success(request, f'You joined {chama.name}.')
            return redirect('dashboard')

        national_id = normalize_national_id(request.POST.get('national_id'))
        if not national_id:
            messages.error(request, 'Enter the National ID the chairperson used when registering you, or ask them to create a one-time invitation link.')
        else:
            # Normalize while scanning so older records containing spaces or
            # hyphens still match IDs entered in the usual unformatted form.
            with db_transaction.atomic():
                candidates = list(
                    Membership.objects.select_for_update().filter(
                        chama=chama, is_active=True,
                    ).exclude(national_id__isnull=True)
                )
                matches = [
                    candidate for candidate in candidates
                    if normalize_national_id(candidate.national_id) == national_id
                ]
                member = matches[0] if len(matches) == 1 else None

                if member is None:
                    messages.error(request, 'We could not match that ID to an active member record in this chama. Check that the chairperson entered the same ID, or ask them to update your record or create a one-time invitation link.')
                elif member.user_id == request.user.id:
                    request.session['active_chama_id'] = chama.pk
                    messages.info(request, f'Your account is already linked to {chama.name}.')
                    return redirect('dashboard')
                elif member.user_id is not None:
                    messages.error(request, 'This member record is already linked to an account. Ask the chairperson to check the registration or issue a new invitation for the correct member record.')
                elif Membership.objects.filter(user=request.user, chama=chama).exists():
                    messages.error(request, 'Your account is already linked to a member record in this chama.')
                else:
                    member.user = request.user
                    member.save(update_fields=['user'])
                    request.session['active_chama_id'] = chama.pk
                    messages.success(request, f'You joined {chama.name}.')
                    return redirect('dashboard')
    return render(request, 'groups/join_chama.html', {
        'chama': chama, 'invite_token': invite_token,
        'invited_membership': invited_membership,
        'entered_national_id': request.POST.get('national_id', ''),
    })


@login_required
@require_POST
def issue_member_invite(request, member_id):
    member = get_object_or_404(Membership.objects.select_related('chama'), pk=member_id)
    if not is_chama_role(request.user, member.chama, 'CHAIRPERSON'):
        raise PermissionDenied('Only the chairperson can invite members.')
    if not member.is_active or member.user_id:
        messages.error(request, 'This member is inactive or already linked to an account.')
        return redirect('members')

    token = signing.dumps(
        {'membership_id': member.pk, 'chama_id': member.chama_id},
        salt='chama-member-invite',
    )
    invite_path = reverse('join_chama', args=[member.chama_id])
    invite_url = request.build_absolute_uri(f'{invite_path}?{urlencode({"invite": token})}')
    request.session['member_invite_url'] = invite_url
    request.session['member_invite_name'] = member.full_name
    messages.success(request, f'Invitation link created for {member.full_name}. It expires in 7 days and can be used once.')
    return redirect('members')


def payment_error(message, status_code=400, transaction_id=None):
    """Return a consistent JSON error response."""
    data = {
        'success': False,
        'error': str(message),
        'message': str(message),
    }

    if transaction_id is not None:
        data['transaction_id'] = transaction_id

    return JsonResponse(data, status=status_code)


def normalize_phone(phone_number):
    """Normalize a Kenyan phone number to 254XXXXXXXXX."""
    phone_number = re.sub(r'[\s\-+]', '', str(phone_number))

    if phone_number.startswith('0') and len(phone_number) == 10:
        phone_number = '254' + phone_number[1:]
    elif len(phone_number) == 9 and phone_number[0] in ('7', '1'):
        phone_number = '254' + phone_number

    if not re.fullmatch(r'254[17]\d{8}', phone_number):
        raise ValueError(
            'Enter a valid Kenyan mobile number, e.g. 0712345678.'
        )

    return phone_number


# =========================
# DASHBOARD
# =========================

@login_required
def dashboard(request):
    profile, created = UserProfile.objects.get_or_create(
        user=request.user
    )

    requested_chama = request.GET.get('chama')
    if requested_chama:
        request.session['active_chama_id'] = requested_chama
    membership = get_user_membership(
        request.user, request.session.get('active_chama_id')
    )
    memberships = Membership.objects.filter(
        user=request.user
    ).select_related('chama').order_by('chama__name')
    personal_contributions = Decimal('0.00')
    personal_loans = Decimal('0.00')
    personal_outstanding = Decimal('0.00')
    if membership:
        personal_contributions = Contribution.objects.filter(
            membership=membership
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        member_loans = Loan.objects.filter(membership=membership)
        personal_loans = member_loans.aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')
        personal_outstanding = sum(
            (loan.outstanding_balance for loan in member_loans.filter(status='APPROVED')),
            start=Decimal('0.00'),
        )
    personal_balance = personal_contributions - personal_outstanding
    contribution_cycle = get_contribution_cycle(membership) if membership else None

    is_official = (
        request.user.is_superuser
        or (
            membership is not None
            and membership.role in OFFICIAL_ROLES
        )
    )

    context = {
        'personal_contributions': personal_contributions,
        'personal_loans': personal_loans,
        'personal_outstanding': personal_outstanding,
        'personal_balance': personal_balance,
        'profile': profile,
        'membership': membership,
        'is_official': is_official,
        'memberships': memberships,
        'contribution_cycle': contribution_cycle,
    }

    return render(request, 'groups/dashboard.html', context)


# =========================
# MEMBERS
# =========================

@login_required
def members(request):
    membership = get_user_membership(request.user, request.session.get('active_chama_id'))

    if request.user.is_superuser:
        all_members = Membership.objects.select_related(
            'chama', 'user'
        ).filter(is_active=True)
    elif membership and membership.role in {'CHAIRPERSON', 'TREASURER', 'SECRETARY'}:
        all_members = Membership.objects.filter(
            chama=membership.chama, is_active=True
        ).select_related('chama', 'user')
    else:
        all_members = Membership.objects.filter(
            user=request.user, is_active=True
        ).select_related('chama', 'user')

    return render(
        request,
        'groups/members.html',
        {
            'members': all_members,
            'membership': membership,
            'can_manage_members': bool(membership and is_chama_role(
                request.user, membership.chama, 'CHAIRPERSON'
            )),
            'can_view_member_finances': bool(membership and membership.role in OFFICIAL_ROLES),
            'invite_url': request.session.pop('member_invite_url', ''),
            'invite_member_name': request.session.pop('member_invite_name', ''),
        }
    )


@login_required
def register_member(request):
    membership = get_user_membership(
        request.user, request.session.get('active_chama_id')
    )

    if not request.user.is_superuser and not (
        membership and is_chama_role(request.user, membership.chama, 'CHAIRPERSON')
    ):
        raise PermissionDenied(
            'Only an authorized chama official can register members.'
        )

    if request.method == 'POST':
        form = MembershipForm(request.POST)

        if not request.user.is_superuser:
            form.fields['chama'].queryset = Chama.objects.filter(
                pk=membership.chama_id
            )

        if form.is_valid():
            new_member = form.save(commit=False)

            if not request.user.is_superuser:
                new_member.chama = membership.chama

            new_member.save()

            return redirect('members')
    else:
        form = MembershipForm()

        if membership and not request.user.is_superuser:
            form.fields['chama'].queryset = Chama.objects.filter(
                pk=membership.chama_id
            )

    return render(
        request,
        'groups/register_member.html',
        {'form': form}
    )


@login_required
def edit_member(request, member_id):
    member = get_object_or_404(
        Membership.objects.select_related('chama'),
        id=member_id
    )

    if not is_chama_role(request.user, member.chama, 'CHAIRPERSON'):
        raise PermissionDenied(
            'You are not authorized to edit this member.'
        )

    if request.method == 'POST':
        form = MembershipForm(request.POST, instance=member)
        form.fields['chama'].queryset = Chama.objects.filter(
            pk=member.chama_id
        )
        form.fields['role'].disabled = True

        if form.is_valid():
            edited_member = form.save(commit=False)

            edited_member.chama = member.chama
            edited_member.role = member.role
            edited_member.user = member.user
            edited_member.save()

            return redirect('members')
    else:
        form = MembershipForm(instance=member)
        form.fields['chama'].queryset = Chama.objects.filter(
            pk=member.chama_id
        )
        form.fields['role'].disabled = True

    return render(
        request,
        'groups/edit_member.html',
        {'form': form, 'member': member}
    )


@login_required
def delete_member(request, member_id):
    member = get_object_or_404(
        Membership.objects.select_related('chama'),
        id=member_id
    )

    if not is_chama_role(request.user, member.chama, 'CHAIRPERSON'):
        raise PermissionDenied(
            'You are not authorized to delete this member.'
        )

    if request.method == 'POST':
        member.is_active = False
        member.user = None
        member.save(update_fields=['is_active', 'user'])
        return redirect('members')

    return render(
        request,
        'groups/delete_member.html',
        {'member': member}
    )


# =========================
# CHAMAS
# =========================

@login_required
def create_chama(request):
    if request.method == 'POST':
        form = ChamaForm(request.POST)

        if form.is_valid():
            with db_transaction.atomic():
                chama = form.save(commit=False)
                chama.created_by = request.user
                chama.save()
                chair = Membership.objects.create(
                    user=request.user,
                    chama=chama,
                    full_name=request.user.get_full_name() or request.user.username,
                    phone_number=form.cleaned_data['chair_phone'],
                    national_id=form.cleaned_data['chair_national_id'].strip() or None,
                    role='CHAIRPERSON',
                )
                request.session['active_chama_id'] = chama.pk
            return redirect('dashboard')
    else:
        form = ChamaForm()

    return render(
        request,
        'groups/create_chama.html',
        {'form': form}
    )


# =========================
# CONTRIBUTIONS
# =========================

@login_required
def contributions(request):
    membership = get_user_membership(request.user, request.session.get('active_chama_id'))

    if request.user.is_superuser:
        all_contributions = Contribution.objects.all()
    elif membership and membership.role in OFFICIAL_ROLES:
        all_contributions = Contribution.objects.filter(
            membership__chama=membership.chama
        )
    else:
        all_contributions = Contribution.objects.filter(
            membership__user=request.user
        )

    all_contributions = all_contributions.select_related(
        'membership', 'membership__chama'
    ).order_by('-contribution_date')

    total_contributions = (
        all_contributions.aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')
    )

    return render(
        request,
        'groups/contributions.html',
        {
            'contributions': all_contributions,
            'membership': membership,
            'total_contributions': total_contributions,
            'can_record_contribution': bool(membership and is_chama_role(
                request.user, membership.chama, 'TREASURER'
            )),
        }
    )


@login_required
def record_contribution(request):
    membership = get_user_membership(request.user, request.session.get('active_chama_id'))

    if not request.user.is_superuser and not (
        membership and is_chama_role(request.user, membership.chama, 'TREASURER')
    ):
        raise PermissionDenied(
            'Only an authorized official can record contributions manually.'
        )

    if request.method == 'POST':
        form = ContributionForm(request.POST)

        if not request.user.is_superuser:
            form.fields['membership'].queryset = Membership.objects.filter(
                chama=membership.chama
            )

        if form.is_valid():
            contribution = form.save()
            log_financial_activity(
                request.user, contribution.membership.chama,
                'Contribution recorded',
                f'{contribution.membership.full_name}: KSh {contribution.amount}',
                contribution,
            )
            return redirect('contributions')
    else:
        form = ContributionForm()

        if membership and not request.user.is_superuser:
            form.fields['membership'].queryset = Membership.objects.filter(
                chama=membership.chama
            )

    return render(
        request,
        'groups/record_contribution.html',
        {'form': form}
    )


# =========================
# LOANS
# =========================

@login_required
def loans(request):
    membership = get_user_membership(request.user, request.session.get('active_chama_id'))

    if request.user.is_superuser:
        all_loans = Loan.objects.all()
    elif membership and membership.role in {'CHAIRPERSON', 'TREASURER'}:
        all_loans = Loan.objects.filter(
            membership__chama=membership.chama
        )
    else:
        all_loans = Loan.objects.filter(
            membership__user=request.user
        )

    all_loans = all_loans.select_related(
        'membership', 'membership__chama'
    ).order_by('-applied_at')

    if request.method == 'POST':
        loan_id = request.POST.get('loan_id')
        action = request.POST.get('action')
        loan = get_object_or_404(all_loans, id=loan_id)

        if not request.user.is_superuser and not (
            is_chama_role(request.user, loan.membership.chama, 'CHAIRPERSON')
        ):
            raise PermissionDenied(
                'Only authorized officials can approve or reject loans.'
            )

        if loan.status == 'PENDING':
            if action == 'approve':
                loan.status = 'APPROVED'
                loan.save(update_fields=['status'])
                log_financial_activity(
                    request.user, loan.membership.chama, 'Loan approved',
                    f'{loan.membership.full_name}: KSh {loan.amount}', loan,
                )
            elif action == 'reject':
                loan.status = 'REJECTED'
                loan.save(update_fields=['status'])
                log_financial_activity(
                    request.user, loan.membership.chama, 'Loan rejected',
                    f'{loan.membership.full_name}: KSh {loan.amount}', loan,
                )

        return redirect('loans')

    return render(
        request,
        'groups/loans.html',
        {
            'loans': all_loans,
            'membership': membership,
            'can_approve': bool(membership and is_chama_role(
                request.user, membership.chama, 'CHAIRPERSON'
            )),
            'can_record_repayment': bool(membership and is_chama_role(
                request.user, membership.chama, 'TREASURER'
            )),
        }
    )


@login_required
def apply_for_loan(request):
    user_memberships = Membership.objects.filter(user=request.user)
    membership = get_user_membership(request.user, request.session.get('active_chama_id'))

    if not user_memberships.exists() and not request.user.is_superuser:
        raise PermissionDenied(
            'Your login account is not linked to a membership yet.'
        )

    if request.method == 'POST':
        form = LoanForm(request.POST)

        if not request.user.is_superuser:
            form.fields['membership'].queryset = user_memberships

        if form.is_valid():
            loan = form.save(commit=False)

            if not request.user.is_superuser:
                loan.membership = form.cleaned_data['membership']

            loan.status = 'PENDING'
            loan.save()
            log_financial_activity(
                request.user, loan.membership.chama, 'Loan requested',
                f'{loan.membership.full_name}: KSh {loan.amount}', loan,
            )

            return redirect('loans')
    else:
        form = LoanForm()

        if not request.user.is_superuser:
            form.fields['membership'].queryset = user_memberships

    return render(
        request,
        'groups/apply_for_loan.html',
        {'form': form}
    )


@login_required
def record_loan_repayment(request):
    membership = get_user_membership(request.user, request.session.get('active_chama_id'))

    if not request.user.is_superuser and not (
        membership and is_chama_role(request.user, membership.chama, 'TREASURER')
    ):
        raise PermissionDenied(
            'Only authorized officials can manually record repayments.'
        )

    if request.method == 'POST':
        form = LoanRepaymentForm(request.POST)

        if not request.user.is_superuser:
            form.fields['loan'].queryset = Loan.objects.filter(
                membership__chama=membership.chama,
                status='APPROVED'
            )

        if form.is_valid():
            repayment = form.save(commit=False)
            loan = repayment.loan

            if loan.status != 'APPROVED':
                form.add_error(
                    'loan',
                    'Repayments can only be recorded for approved loans.'
                )
            elif repayment.amount <= 0:
                form.add_error(
                    'amount',
                    'The repayment amount must be greater than zero.'
                )
            elif repayment.amount > loan.outstanding_balance:
                form.add_error(
                    'amount',
                    'The repayment exceeds the outstanding loan balance.'
                )
            else:
                repayment.save()
                log_financial_activity(
                    request.user, loan.membership.chama, 'Repayment recorded',
                    f'{loan.membership.full_name}: KSh {repayment.amount}', repayment,
                )
                loan.refresh_from_db()

                if loan.outstanding_balance <= 0:
                    loan.status = 'REPAID'
                    loan.save(update_fields=['status'])

                return redirect('loans')
    else:
        form = LoanRepaymentForm()

        if not request.user.is_superuser:
            form.fields['loan'].queryset = Loan.objects.filter(
                membership__chama=membership.chama,
                status='APPROVED'
            )

    return render(
        request,
        'groups/record_loan_repayment.html',
        {'form': form}
    )


# =========================
# FINANCIAL REPORTS
# =========================

@login_required
def financial_reports(request):
    membership = get_user_membership(request.user, request.session.get('active_chama_id'))

    if request.user.is_superuser:
        chamas = Chama.objects.all().order_by('name')
    elif membership and membership.role in OFFICIAL_ROLES:
        chamas = Chama.objects.filter(pk=membership.chama_id)
    elif membership:
        # Members get their own report; group totals remain official-only.
        return redirect('member_financial_history', membership_id=membership.pk)
    else:
        raise PermissionDenied(
            'Only authorized officials can view financial reports.'
        )

    total_contributions = Contribution.objects.filter(
        membership__chama__in=chamas
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    total_loans = Loan.objects.filter(
        membership__chama__in=chamas,
        status__in=['APPROVED', 'REPAID']
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    total_repayments = LoanRepayment.objects.filter(
        loan__membership__chama__in=chamas
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    total_outstanding = sum(
        (
            loan.outstanding_balance
            for loan in Loan.objects.filter(
                membership__chama__in=chamas,
                status='APPROVED'
            )
        ),
        start=Decimal('0.00')
    )
    total_other_income = ChamaCashflowEntry.objects.filter(
        chama__in=chamas, entry_type='INCOME'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    total_expenses = ChamaCashflowEntry.objects.filter(
        chama__in=chamas, entry_type='EXPENSE'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    total_fines_outstanding = sum(
        (fine.balance for fine in MemberFine.objects.filter(membership__chama__in=chamas)),
        start=Decimal('0.00'),
    )

    recent_activity = FinancialActivity.objects.filter(
        chama__in=chamas
    ).select_related('chama', 'actor')[:30]

    chama_reports = []

    for chama in chamas:
        contributions_total = Contribution.objects.filter(
            membership__chama=chama
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        chama_loans = Loan.objects.filter(
            membership__chama=chama,
            status__in=['APPROVED', 'REPAID']
        )

        loans_issued = chama_loans.aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')

        repayments_total = LoanRepayment.objects.filter(
            loan__membership__chama=chama
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        chama_income = ChamaCashflowEntry.objects.filter(
            chama=chama, entry_type='INCOME'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        chama_expenses = ChamaCashflowEntry.objects.filter(
            chama=chama, entry_type='EXPENSE'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        outstanding = sum(
            (
                loan.outstanding_balance
                for loan in Loan.objects.filter(
                    membership__chama=chama,
                    status='APPROVED'
                )
            ),
            start=Decimal('0.00')
        )

        chama_reports.append({
            'chama': chama,
            'contributions': contributions_total,
            'loans_issued': loans_issued,
            'repayments': repayments_total,
            'outstanding': outstanding,
            'other_income': chama_income,
            'expenses': chama_expenses,
        })

    return render(
        request,
        'groups/financial_reports.html',
        {
            'total_contributions': total_contributions,
            'total_loans': total_loans,
            'total_repayments': total_repayments,
            'total_outstanding': total_outstanding,
            'total_other_income': total_other_income,
            'total_expenses': total_expenses,
            'total_fines_outstanding': total_fines_outstanding,
            'chama_reports': chama_reports,
            'can_print_chama_report': True,
            'recent_activity': recent_activity,
        }
    )


# =========================
# MEMBER FINANCIAL HISTORY
# =========================

@login_required
def group_finances(request):
    membership = get_user_membership(request.user, request.session.get('active_chama_id'))
    if request.user.is_superuser and membership is None:
        chama = Chama.objects.order_by('name').first()
    else:
        chama = membership.chama if membership else None
    if chama is None:
        raise PermissionDenied('Join a chama before viewing its finance records.')

    can_manage = is_chama_role(request.user, chama, 'TREASURER')
    can_view_all = request.user.is_superuser or is_chama_official(request.user, chama)
    if not can_manage and request.method == 'POST':
        raise PermissionDenied('Only the treasurer can record expenses, income, fines, or fine payments.')

    cashflow_form = ChamaCashflowEntryForm()
    fine_form = MemberFineForm()
    payment_form = FinePaymentForm()
    members_in_chama = Membership.objects.filter(chama=chama, is_active=True).order_by('full_name')
    outstanding_fines = MemberFine.objects.filter(membership__chama=chama).select_related('membership')
    if not can_view_all:
        outstanding_fines = outstanding_fines.filter(membership=membership)
    outstanding_fines = [fine for fine in outstanding_fines if fine.balance > 0]

    if can_manage:
        fine_form.fields['membership'].queryset = members_in_chama
        payment_form.fields['fine'].queryset = MemberFine.objects.filter(
            membership__chama=chama
        ).select_related('membership')

    if request.method == 'POST':
        form_type = request.POST.get('form_type')
        if form_type == 'rotation_setup':
            if chama.savings_model != 'MERRY_GO_ROUND':
                raise PermissionDenied('Rotation schedules are only available for merry-go-round groups.')
            if chama.rotation_payouts.exists():
                messages.info(request, 'A payout rotation already exists for this group.')
                return redirect('group_finances')
            roster = list(members_in_chama.order_by('joined_at', 'id'))
            if len(roster) < 2:
                messages.error(request, 'Add at least two active members before creating a payout rotation.')
                return redirect('group_finances')
            today = timezone.localdate()
            if chama.contribution_frequency == 'WEEKLY':
                first_due = today - timedelta(days=today.weekday()) + timedelta(days=chama.contribution_due_day - 1)
                if first_due <= today:
                    first_due += timedelta(days=7)
            else:
                first_due = today.replace(day=chama.contribution_due_day)
                if first_due <= today:
                    first_due = add_months(first_due, 1)
            payout_amount = chama.contribution_amount * len(roster)
            with db_transaction.atomic():
                for turn, recipient in enumerate(roster, start=1):
                    scheduled_date = first_due + timedelta(days=7 * (turn - 1)) if chama.contribution_frequency == 'WEEKLY' else add_months(first_due, turn - 1)
                    RotationPayout.objects.create(
                        chama=chama, turn_number=turn, recipient=recipient,
                        scheduled_date=scheduled_date, amount=payout_amount,
                    )
            log_financial_activity(request.user, chama, 'Payout rotation created', f'{len(roster)} turns, KSh {payout_amount} per turn')
            messages.success(request, f'Created a {len(roster)}-turn payout rotation.')
            return redirect('group_finances')
        elif form_type == 'mark_payout_paid':
            payout = get_object_or_404(RotationPayout.objects.select_related('recipient'), pk=request.POST.get('payout_id'), chama=chama)
            if payout.status == 'PAID':
                messages.info(request, 'This payout is already marked paid.')
                return redirect('group_finances')
            with db_transaction.atomic():
                payout = RotationPayout.objects.select_for_update().get(pk=payout.pk)
                if payout.status == 'PAID':
                    messages.info(request, 'This payout is already marked paid.')
                    return redirect('group_finances')
                payout.status = 'PAID'
                payout.paid_at = timezone.now()
                payout.recorded_by = request.user
                payout.save(update_fields=['status', 'paid_at', 'recorded_by'])
                ChamaCashflowEntry.objects.create(
                    chama=chama, entry_type='EXPENSE', category='Merry-go-round payout',
                    description=f'Turn {payout.turn_number} paid to {payout.recipient.full_name}',
                    amount=payout.amount, entry_date=timezone.localdate(), recorded_by=request.user,
                )
                log_financial_activity(request.user, chama, 'Merry-go-round payout recorded', f'Turn {payout.turn_number} to {payout.recipient.full_name}: KSh {payout.amount}', payout)
            messages.success(request, 'Payout marked paid and added to group expenses.')
            return redirect('group_finances')
        elif form_type == 'cashflow':
            cashflow_form = ChamaCashflowEntryForm(request.POST)
            if cashflow_form.is_valid():
                entry = cashflow_form.save(commit=False)
                entry.chama, entry.recorded_by = chama, request.user
                entry.save()
                log_financial_activity(request.user, chama, entry.get_entry_type_display(), f'{entry.category}: KSh {entry.amount}', entry)
                messages.success(request, 'Financial entry recorded.')
                return redirect('group_finances')
        elif form_type == 'fine':
            fine_form = MemberFineForm(request.POST)
            fine_form.fields['membership'].queryset = members_in_chama
            if fine_form.is_valid():
                fine = fine_form.save(commit=False)
                fine.issued_by = request.user
                fine.save()
                log_financial_activity(request.user, chama, 'Fine issued', f'{fine.membership.full_name}: KSh {fine.amount} ({fine.get_category_display()})', fine)
                messages.success(request, 'Fine added to the member account.')
                return redirect('group_finances')
        elif form_type == 'fine_payment':
            payment_form = FinePaymentForm(request.POST)
            payment_form.fields['fine'].queryset = MemberFine.objects.filter(membership__chama=chama).select_related('membership')
            if payment_form.is_valid():
                payment = payment_form.save(commit=False)
                fine = payment.fine
                if payment.amount > fine.balance:
                    payment_form.add_error('amount', 'Payment exceeds the fine balance.')
                else:
                    payment.recorded_by = request.user
                    with db_transaction.atomic():
                        payment.save()
                        ChamaCashflowEntry.objects.create(
                            chama=chama, entry_type='INCOME', category='Fine payment',
                            description=f'Fine payment from {fine.membership.full_name}',
                            amount=payment.amount, entry_date=timezone.localdate(), recorded_by=request.user,
                            reference=payment.reference,
                        )
                        log_financial_activity(request.user, chama, 'Fine payment recorded', f'{fine.membership.full_name}: KSh {payment.amount}', payment)
                    messages.success(request, 'Fine payment recorded.')
                    return redirect('group_finances')

    entries = ChamaCashflowEntry.objects.filter(chama=chama).select_related('recorded_by')[:100]
    income = ChamaCashflowEntry.objects.filter(chama=chama, entry_type='INCOME').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    expenses = ChamaCashflowEntry.objects.filter(chama=chama, entry_type='EXPENSE').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    fines = MemberFine.objects.filter(membership__chama=chama).select_related('membership').prefetch_related('payments')
    if not can_view_all:
        fines = fines.filter(membership=membership)
    rotation_payouts = RotationPayout.objects.filter(chama=chama).select_related('recipient')
    return render(request, 'groups/group_finances.html', {
        'chama': chama, 'can_manage': can_manage, 'cashflow_form': cashflow_form,
        'can_view_report': can_view_all,
        'fine_form': fine_form, 'payment_form': payment_form, 'entries': entries,
        'income': income, 'expenses': expenses, 'net_other_income': income-expenses,
        'fines': fines, 'outstanding_fines': outstanding_fines,
        'rotation_payouts': rotation_payouts,
    })

@login_required
def member_financial_history(request, membership_id):
    membership = get_object_or_404(
        Membership.objects.select_related('chama', 'user'),
        id=membership_id
    )

    own_record = membership.user_id == request.user.id
    authorized_official = is_chama_official(
        request.user, membership.chama
    )

    if not own_record and not authorized_official:
        raise PermissionDenied(
            "You are not allowed to view this member's financial history."
        )

    contributions = Contribution.objects.filter(
        membership=membership
    ).order_by('-contribution_date')

    member_loans = Loan.objects.filter(
        membership=membership
    ).order_by('-applied_at')

    repayments = LoanRepayment.objects.filter(
        loan__membership=membership
    ).order_by('-payment_date')
    member_fines = MemberFine.objects.filter(
        membership=membership
    ).prefetch_related('payments')
    mpesa_transactions = MpesaTransaction.objects.filter(
        membership=membership
    ).order_by('-created_at')

    if request.GET.get('download') == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        safe_name = re.sub(r'[^A-Za-z0-9_-]+', '_', membership.full_name).strip('_') or 'member'
        response['Content-Disposition'] = f'attachment; filename="{safe_name}_financial_history.csv"'
        writer = csv.writer(response)
        writer.writerow(['Member', membership.full_name])
        writer.writerow(['Chama', membership.chama.name])
        writer.writerow([])
        writer.writerow(['Date', 'Record type', 'Description', 'Amount (KSh)', 'Status / reference'])
        for contribution in contributions:
            writer.writerow([
                timezone.localtime(contribution.contribution_date).strftime('%Y-%m-%d %H:%M'),
                'Contribution', contribution.get_payment_method_display(), contribution.amount,
                contribution.reference,
            ])
        for loan in member_loans:
            writer.writerow([
                timezone.localtime(loan.applied_at).strftime('%Y-%m-%d %H:%M'),
                'Loan', f'Interest rate: {loan.interest_rate}%', loan.amount,
                loan.get_status_display(),
            ])
        for repayment in repayments:
            writer.writerow([
                timezone.localtime(repayment.payment_date).strftime('%Y-%m-%d %H:%M'),
                'Loan repayment', repayment.get_payment_method_display(), repayment.amount,
                repayment.reference,
            ])
        for fine in member_fines:
            writer.writerow([
                timezone.localtime(fine.issued_at).strftime('%Y-%m-%d %H:%M'),
                'Fine issued', fine.get_category_display() + ': ' + fine.description,
                fine.amount, f'Balance KSh {fine.balance}',
            ])
            for payment in fine.payments.all():
                writer.writerow([
                    timezone.localtime(payment.paid_at).strftime('%Y-%m-%d %H:%M'),
                    'Fine payment', payment.get_payment_method_display(), payment.amount,
                    payment.reference,
                ])
        for transaction in mpesa_transactions:
            writer.writerow([
                timezone.localtime(transaction.created_at).strftime('%Y-%m-%d %H:%M'),
                f'M-Pesa {transaction.get_transaction_type_display()}',
                transaction.phone_number, transaction.amount,
                transaction.get_status_display() + (f' / {transaction.receipt_number}' if transaction.receipt_number else ''),
            ])
        return response

    return render(
        request,
        'groups/member_financial_history.html',
        {
            'membership': membership,
            'contributions': contributions,
            'loans': member_loans,
            'repayments': repayments,
            'fines': member_fines,
            'mpesa_transactions': mpesa_transactions,
            'can_print_individual_report': own_record or request.user.is_superuser or is_chama_role(request.user, membership.chama, 'CHAIRPERSON'),
        }
    )


# =========================
# M-PESA PAYMENT PAGE
# =========================

@login_required
def mpesa_payment_page(request):
    if os.getenv('CHAMALINK_DEMO_MODE', '').lower() == 'true':
        return render(
            request,
            'groups/mpesa_payment.html',
            {'demo_mode': True, 'members': [], 'loans': []},
        )

    membership = get_user_membership(request.user, request.session.get('active_chama_id'))

    if request.user.is_superuser:
        members_list = Membership.objects.all()
        approved_loans = Loan.objects.filter(status='APPROVED')
    elif membership and membership.role == 'TREASURER':
        members_list = Membership.objects.filter(
            chama=membership.chama
        )
        if membership.role == 'TREASURER':
            approved_loans = Loan.objects.filter(
                membership__chama=membership.chama,
                status='APPROVED'
            )
        else:
            approved_loans = Loan.objects.filter(
                membership__user=request.user,
                status='APPROVED'
            )
    else:
        members_list = Membership.objects.filter(user=request.user)
        approved_loans = Loan.objects.filter(
            membership__user=request.user,
            status='APPROVED'
        )

    return render(
        request,
        'groups/mpesa_payment.html',
        {
            'members': members_list.select_related(
                'chama'
            ).order_by('full_name'),
            'loans': approved_loans.select_related(
                'membership', 'membership__chama'
            ).order_by('-applied_at'),
        }
    )


# =========================
# INITIATE M-PESA STK PUSH
# =========================

@login_required
@require_POST
def initiate_mpesa_payment(request):
    if os.getenv('CHAMALINK_DEMO_MODE', '').lower() == 'true':
        return payment_error('M-Pesa payments are disabled in the public demo.', 403)

    membership_id = request.POST.get('membership_id', '').strip()
    transaction_type = request.POST.get(
        'transaction_type', 'contribution'
    ).strip().lower()
    amount_value = request.POST.get('amount', '').strip()
    phone_value = request.POST.get('phone_number', '').strip()
    loan_id = request.POST.get('loan_id', '').strip()

    if not membership_id or not amount_value or not phone_value:
        return payment_error(
            'Member, amount, and phone number are required.'
        )

    if transaction_type not in (
        MpesaTransaction.Type.CONTRIBUTION,
        MpesaTransaction.Type.LOAN_REPAYMENT,
    ):
        return payment_error('Choose a valid payment type.')

    try:
        membership = Membership.objects.select_related('chama').get(
            pk=membership_id
        )
    except (Membership.DoesNotExist, ValueError, TypeError):
        return payment_error('The selected member was not found.', 404)

    if not request.user.is_superuser:
        own_member = membership.user_id == request.user.id
        official = is_chama_role(request.user, membership.chama, 'TREASURER')

        if not own_member and not official:
            return payment_error(
                'You are not authorized to pay for this membership.',
                403
            )

    try:
        amount_decimal = Decimal(amount_value)

        if (
            not amount_decimal.is_finite()
            or amount_decimal <= 0
            or amount_decimal != amount_decimal.to_integral_value()
        ):
            raise ValueError

        amount = int(amount_decimal)

    except (InvalidOperation, ValueError, TypeError):
        return payment_error(
            'Enter a positive whole-number amount in KSh.'
        )

    try:
        phone_number = normalize_phone(phone_value)
    except ValueError as exc:
        return payment_error(str(exc))

    loan = None

    if transaction_type == MpesaTransaction.Type.LOAN_REPAYMENT:
        if not loan_id:
            return payment_error('Select a loan to repay.')

        try:
            loan = Loan.objects.get(
                pk=loan_id,
                membership=membership,
            )
        except (Loan.DoesNotExist, ValueError, TypeError):
            return payment_error(
                'The selected loan does not belong to this member.',
                404
            )

        if loan.status != 'APPROVED':
            return payment_error(
                'Only approved loans can receive repayments.'
            )

        if Decimal(amount) > Decimal(str(loan.outstanding_balance)):
            return payment_error(
                'The amount exceeds the outstanding loan balance.'
            )

    callback_url = getattr(settings, 'MPESA_CALLBACK_URL', '')

    if not callback_url or not callback_url.startswith('https://'):
        return payment_error(
            'Configure MPESA_CALLBACK_URL with a public HTTPS callback URL.',
            500
        )

    # Create the local record before sending the request.
    payment = MpesaTransaction.objects.create(
        membership=membership,
        loan=loan,
        transaction_type=transaction_type,
        amount=Decimal(amount),
        phone_number=phone_number,
        status=MpesaTransaction.Status.PENDING,
    )

    try:
        result = initiate_stk_push(
            phone_number=phone_number,
            amount=amount,
            callback_url=callback_url,
            account_reference=f'CHAMA{payment.id}',
            description=(
                'Chama contribution'
                if transaction_type == MpesaTransaction.Type.CONTRIBUTION
                else 'Chama loan repayment'
            ),
        )

        if not isinstance(result, dict):
            logger.error(
                'Unexpected STK Push response for transaction %s',
                payment.pk
            )
            return JsonResponse({
                'success': True,
                'message': (
                    'The request may have been sent. Check your phone '
                    'and confirm the payment status before retrying.'
                ),
                'transaction_id': payment.pk,
                'status': payment.status,
            }, status=202)

        response_code = str(result.get('ResponseCode', ''))
        checkout_request_id = result.get('CheckoutRequestID')

        if response_code != '0' or not checkout_request_id:
            payment.status = MpesaTransaction.Status.FAILED
            payment.result_desc = (
                result.get('ResponseDescription')
                or result.get('errorMessage')
                or 'Safaricom did not accept the STK Push request.'
            )[:255]
            payment.save(
                update_fields=['status', 'result_desc', 'updated_at']
            )

            return payment_error(
                payment.result_desc,
                502,
                payment.pk
            )

        payment.checkout_request_id = checkout_request_id
        payment.merchant_request_id = (
            result.get('MerchantRequestID') or ''
        )[:100]
        payment.save(update_fields=[
            'checkout_request_id',
            'merchant_request_id',
            'updated_at',
        ])

        logger.info('STK Push accepted for transaction %s', payment.pk)

        return JsonResponse({
            'success': True,
            'message': (
                'STK Push request accepted. Check your phone and follow '
                'the M-Pesa prompt. Payment is not yet confirmed.'
            ),
            'transaction_id': payment.pk,
            'status': payment.status,
        })

    except (requests.RequestException, ValueError, InvalidOperation):
        # A timeout may happen after Safaricom has received the request.
        # Keep it pending until its outcome can be confirmed.
        logger.exception('STK Push error for transaction %s', payment.pk)

        return JsonResponse({
            'success': True,
            'message': (
                'We could not confirm the STK Push response. Check your '
                'phone and verify the transaction before trying again.'
            ),
            'transaction_id': payment.pk,
            'status': payment.status,
        }, status=202)

    except Exception:
        logger.exception(
            'Unexpected STK Push error for transaction %s',
            payment.pk
        )

        return JsonResponse({
            'success': True,
            'message': (
                'The request outcome is uncertain. Check your phone and '
                'verify the transaction before trying again.'
            ),
            'transaction_id': payment.pk,
            'status': payment.status,
        }, status=202)


# =========================
# M-PESA CALLBACK
# =========================

@csrf_exempt
@require_POST
def mpesa_callback(request):
    """
    Processes Safaricom STK callbacks.

    For production, add independent callback verification and transaction
    reconciliation. Do not treat an unverified HTTP request as proof of payment.
    """
    try:
        payload = json.loads(request.body.decode('utf-8'))
        callback = payload['Body']['stkCallback']

        checkout_request_id = callback.get('CheckoutRequestID')
        result_code = int(callback.get('ResultCode', -1))
        result_desc = str(callback.get('ResultDesc', ''))[:255]

        if not checkout_request_id:
            return JsonResponse(
                {'ResultCode': 1, 'ResultDesc': 'Missing checkout request ID'},
                status=400
            )

    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ):
        logger.warning('Invalid M-Pesa callback payload.')
        return JsonResponse(
            {'ResultCode': 1, 'ResultDesc': 'Invalid callback payload'},
            status=400
        )

    try:
        with db_transaction.atomic():
            payment = (
                MpesaTransaction.objects
                .select_for_update()
                .filter(checkout_request_id=checkout_request_id)
                .first()
            )

            if payment is None:
                logger.warning('Callback for unknown checkout request.')
                return JsonResponse({
                    'ResultCode': 0,
                    'ResultDesc': 'Callback received',
                })

            # Ignore repeated callbacks after a final result.
            if payment.status in (
                MpesaTransaction.Status.SUCCESS,
                MpesaTransaction.Status.FAILED,
            ):
                return JsonResponse({
                    'ResultCode': 0,
                    'ResultDesc': 'Already processed',
                })

            payment.result_code = result_code
            payment.result_desc = result_desc

            if result_code != 0:
                payment.status = MpesaTransaction.Status.FAILED
                payment.save(update_fields=[
                    'status',
                    'result_code',
                    'result_desc',
                    'updated_at',
                ])

                return JsonResponse({
                    'ResultCode': 0,
                    'ResultDesc': 'Payment failure recorded',
                })

            metadata = callback.get('CallbackMetadata') or {}
            items = metadata.get('Item') or []

            details = {
                item.get('Name'): item.get('Value')
                for item in items
                if isinstance(item, dict) and item.get('Name')
            }

            receipt = str(
                details.get('MpesaReceiptNumber') or ''
            ).strip()
            paid_amount = details.get('Amount')
            paid_phone = details.get('PhoneNumber')

            if not receipt or paid_amount is None:
                payment.result_desc = (
                    'Successful callback is missing receipt or amount.'
                )
                payment.save(update_fields=[
                    'result_desc',
                    'updated_at',
                ])
                logger.error(
                    'Incomplete successful callback for transaction %s',
                    payment.pk
                )
                return JsonResponse({
                    'ResultCode': 0,
                    'ResultDesc': 'Callback received for reconciliation',
                })

            try:
                callback_amount = Decimal(str(paid_amount))
            except (InvalidOperation, ValueError, TypeError):
                payment.result_desc = 'Invalid callback payment amount.'
                payment.save(update_fields=[
                    'result_desc',
                    'updated_at',
                ])
                return JsonResponse({
                    'ResultCode': 0,
                    'ResultDesc': 'Callback received for reconciliation',
                })

            if callback_amount != payment.amount:
                payment.result_desc = 'Callback amount mismatch.'
                payment.save(update_fields=[
                    'result_desc',
                    'updated_at',
                ])
                logger.error(
                    'Payment amount mismatch for transaction %s',
                    payment.pk
                )
                return JsonResponse({
                    'ResultCode': 0,
                    'ResultDesc': 'Callback received for reconciliation',
                })

            if (
                paid_phone is not None
                and str(paid_phone) != payment.phone_number
            ):
                payment.result_desc = 'Callback phone number mismatch.'
                payment.save(update_fields=[
                    'result_desc',
                    'updated_at',
                ])
                logger.error(
                    'Phone mismatch for transaction %s',
                    payment.pk
                )
                return JsonResponse({
                    'ResultCode': 0,
                    'ResultDesc': 'Callback received for reconciliation',
                })

            receipt_exists = MpesaTransaction.objects.filter(
                receipt_number=receipt
            ).exclude(pk=payment.pk).exists()

            if receipt_exists:
                payment.result_desc = 'Receipt already linked to another transaction.'
                payment.save(update_fields=[
                    'result_desc',
                    'updated_at',
                ])
                logger.error('Duplicate M-Pesa receipt detected.')
                return JsonResponse({
                    'ResultCode': 0,
                    'ResultDesc': 'Callback received for reconciliation',
                })

            # Record the financial entry and final transaction status together.
            if payment.transaction_type == MpesaTransaction.Type.CONTRIBUTION:
                Contribution.objects.get_or_create(
                    reference=receipt,
                    defaults={
                        'membership': payment.membership,
                        'amount': payment.amount,
                        'payment_method': 'MPESA',
                    },
                )

            elif payment.transaction_type == MpesaTransaction.Type.LOAN_REPAYMENT:
                if payment.loan_id is None:
                    payment.result_desc = 'No loan is linked to this repayment.'
                    payment.save(update_fields=[
                        'result_desc',
                        'updated_at',
                    ])
                    return JsonResponse({
                        'ResultCode': 0,
                        'ResultDesc': 'Callback received for reconciliation',
                    })

                loan = Loan.objects.select_for_update().get(
                    pk=payment.loan_id,
                    membership=payment.membership,
                )

                if loan.status != 'APPROVED':
                    payment.result_desc = (
                        'Loan is not approved; repayment requires reconciliation.'
                    )
                    payment.save(update_fields=[
                        'result_desc',
                        'updated_at',
                    ])
                    return JsonResponse({
                        'ResultCode': 0,
                        'ResultDesc': 'Callback received for reconciliation',
                    })

                if payment.amount > Decimal(str(loan.outstanding_balance)):
                    payment.result_desc = (
                        'Repayment exceeds outstanding balance; '
                        'manual reconciliation required.'
                    )
                    payment.save(update_fields=[
                        'result_desc',
                        'updated_at',
                    ])
                    return JsonResponse({
                        'ResultCode': 0,
                        'ResultDesc': 'Callback received for reconciliation',
                    })

                LoanRepayment.objects.get_or_create(
                    reference=receipt,
                    defaults={
                        'loan': loan,
                        'amount': payment.amount,
                        'payment_method': 'MPESA',
                    },
                )

                loan.refresh_from_db()

                if loan.outstanding_balance <= 0:
                    loan.status = 'REPAID'
                    loan.save(update_fields=['status'])

            else:
                payment.result_desc = 'Unsupported transaction type.'
                payment.save(update_fields=[
                    'result_desc',
                    'updated_at',
                ])
                return JsonResponse({
                    'ResultCode': 0,
                    'ResultDesc': 'Callback received for reconciliation',
                })

            payment.receipt_number = receipt
            payment.status = MpesaTransaction.Status.SUCCESS
            payment.result_desc = result_desc or 'Payment successful.'
            payment.save(update_fields=[
                'receipt_number',
                'status',
                'result_code',
                'result_desc',
                'updated_at',
            ])
            payment_label = (
                'Contribution' if payment.transaction_type == MpesaTransaction.Type.CONTRIBUTION
                else 'Loan repayment'
            )
            log_financial_activity(
                None, payment.membership.chama, 'M-Pesa payment confirmed',
                f'{payment_label}: {payment.membership.full_name}, KSh {payment.amount}, receipt {receipt}',
                payment,
            )

        logger.info('M-Pesa transaction %s processed.', payment.pk)

        return JsonResponse({
            'ResultCode': 0,
            'ResultDesc': 'Payment processed',
        })

    except Exception:
        logger.exception('Error processing M-Pesa callback.')
        return JsonResponse(
            {'ResultCode': 1, 'ResultDesc': 'Callback processing failed'},
            status=500
        )


# =========================
# SETTINGS AND PROFILE PICTURE
# =========================

@login_required
def app_settings(request):
    membership = get_user_membership(request.user, request.session.get('active_chama_id'))

    is_official = (
        request.user.is_superuser
        or (
            membership is not None
            and membership.role in OFFICIAL_ROLES
        )
    )

    profile, created = UserProfile.objects.get_or_create(
        user=request.user
    )

    if request.method == 'POST':
        profile_form = ProfileForm(
            request.POST,
            instance=request.user
        )

        picture_form = ProfilePictureForm(
            request.POST,
            request.FILES,
            instance=profile
        )

        if profile_form.is_valid() and picture_form.is_valid():
            profile_form.save()
            picture_form.save()

            messages.success(
                request,
                'Your profile and picture have been updated successfully.'
            )

            return redirect('app_settings')

    else:
        profile_form = ProfileForm(instance=request.user)
        picture_form = ProfilePictureForm(instance=profile)

    context = {
        'membership': membership,
        'is_official': is_official,
        'profile_form': profile_form,
        'picture_form': picture_form,
        'profile': profile,
    }

    return render(
        request,
        'groups/settings.html',
        context
    )
