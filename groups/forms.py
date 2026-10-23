
from django import forms
import re

from .models import (
    Chama,
    Membership,
    Contribution,
    Loan,
    LoanRepayment,
    ChamaCashflowEntry,
    MemberFine,
    FinePayment,
    SavingsGoal,
    GoalProgressEntry,
    ChamaMeeting,
    MeetingAttendance,
    PlanInquiry,
)


def normalize_national_id(value):
    """Normalize common visual separators while preserving the ID itself."""
    return re.sub(r'[\s-]+', '', value or '').casefold()


class MembershipForm(forms.ModelForm):
    class Meta:
        model = Membership
        fields = [
            'chama',
            'full_name',
            'phone_number',
            'national_id',
            'role',
        ]
        widgets = {
            'chama': forms.Select(attrs={'class': 'form-input'}),
            'full_name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Enter member full name',
            }),
            'phone_number': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Enter phone number',
            }),
            'national_id': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'National ID for self-service joining',
            }),
            'role': forms.Select(attrs={'class': 'form-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not self.instance.pk:
            self.fields['role'].initial = 'MEMBER'
            self.fields['role'].choices = [
                choice for choice in self.fields['role'].choices
                if choice[0] != 'CHAIRPERSON'
            ]

        self.fields['national_id'].help_text = (
            'Enter the member’s National ID so they can find this record and join. '
            'Leave it blank only if you will share a one-time invitation link.'
        )

    def clean_national_id(self):
        national_id = normalize_national_id(self.cleaned_data.get('national_id'))
        return national_id or None

    def clean_role(self):
        role = self.cleaned_data['role']

        if role == 'CHAIRPERSON' and (
            not self.instance.pk or role != self.instance.role
        ):
            raise forms.ValidationError(
                'The chama creator is the chairperson.'
            )

        return role


class ChamaForm(forms.ModelForm):
    chair_phone = forms.CharField(max_length=15, label='Your phone number')
    chair_national_id = forms.CharField(max_length=20, label='Your National ID', required=False)

    class Meta:
        model = Chama
        fields = [
            'name',
            'description',
            'meeting_location',
            'savings_model',
            'contribution_amount',
            'contribution_frequency',
            'contribution_due_day',
            'chair_phone',
            'chair_national_id',
        ]
        help_texts = {
            'savings_model': 'Choose pooled savings and lending or a rotating payout round.',
            'contribution_frequency': 'Choose how often members are expected to contribute.',
            'contribution_due_day': 'Monthly: day 1–28. Weekly: Monday=1 through Sunday=7.',
        }
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Enter chama name',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-input',
                'rows': 4,
                'placeholder': 'Describe your chama',
            }),
            'meeting_location': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Enter meeting location',
            }),
            'contribution_amount': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': '0.01',
                'step': '0.01',
            }),
            'contribution_frequency': forms.Select(attrs={'class': 'form-input'}),
            'contribution_due_day': forms.NumberInput(attrs={
                'class': 'form-input', 'min': '1', 'max': '28',
                'placeholder': '1 to 28 for monthly; 1 to 7 for weekly',
            }),
        }

    def clean_contribution_amount(self):
        amount = self.cleaned_data['contribution_amount']

        if amount <= 0:
            raise forms.ValidationError(
                'The contribution amount must be greater than zero.'
            )

        return amount

    def clean(self):
        cleaned = super().clean()
        day = cleaned.get('contribution_due_day')
        frequency = cleaned.get('contribution_frequency')
        max_day = 7 if frequency == 'WEEKLY' else 28
        if day is not None and not 1 <= day <= max_day:
            self.add_error(
                'contribution_due_day',
                f'Enter a day from 1 to {max_day} for this contribution frequency.'
            )
        return cleaned


class ContributionForm(forms.ModelForm):
    class Meta:
        model = Contribution
        fields = [
            'membership',
            'amount',
            'payment_method',
            'reference',
        ]
        widgets = {
            'membership': forms.Select(attrs={
                'class': 'form-input',
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': '0.01',
                'step': '0.01',
            }),
            'payment_method': forms.Select(attrs={
                'class': 'form-input',
            }),
            'reference': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Payment reference, if available',
            }),
        }

    def clean_amount(self):
        amount = self.cleaned_data['amount']

        if amount <= 0:
            raise forms.ValidationError(
                'The contribution must be greater than zero.'
            )

        return amount


class LoanForm(forms.ModelForm):
    class Meta:
        model = Loan
        fields = [
            'membership',
            'amount',
            'purpose',
            'interest_rate',
            'due_date',
        ]
        widgets = {
            'membership': forms.Select(attrs={
                'class': 'form-input',
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': '0.01',
                'step': '0.01',
            }),
            'purpose': forms.Textarea(attrs={
                'class': 'form-input',
                'rows': 4,
                'placeholder': 'Explain the purpose of the loan',
            }),
            'interest_rate': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': '0',
                'step': '0.01',
            }),
            'due_date': forms.DateInput(attrs={
                'class': 'form-input',
                'type': 'date',
            }),
        }

    def clean_amount(self):
        amount = self.cleaned_data['amount']

        if amount <= 0:
            raise forms.ValidationError(
                'The loan amount must be greater than zero.'
            )

        return amount

    def clean_interest_rate(self):
        rate = self.cleaned_data['interest_rate']

        if rate < 0:
            raise forms.ValidationError(
                'The interest rate cannot be negative.'
            )

        return rate


class LoanRepaymentForm(forms.ModelForm):
    class Meta:
        model = LoanRepayment
        fields = [
            'loan',
            'amount',
            'payment_method',
            'reference',
        ]
        widgets = {
            'loan': forms.Select(attrs={
                'class': 'form-input',
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': '0.01',
                'step': '0.01',
            }),
            'payment_method': forms.Select(attrs={
                'class': 'form-input',
            }),
            'reference': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Payment reference, if available',
            }),
        }

    def clean_amount(self):
        amount = self.cleaned_data['amount']

        if amount <= 0:
            raise forms.ValidationError(
                'The repayment must be greater than zero.'
            )

        return amount


class ChamaCashflowEntryForm(forms.ModelForm):
    class Meta:
        model = ChamaCashflowEntry
        fields = ['entry_type', 'category', 'description', 'amount', 'entry_date', 'reference']
        widgets = {
            'entry_type': forms.Select(attrs={'class': 'form-input'}),
            'category': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. meeting refreshments'}),
            'description': forms.TextInput(attrs={'class': 'form-input'}),
            'amount': forms.NumberInput(attrs={'class': 'form-input', 'min': '0.01', 'step': '0.01'}),
            'entry_date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            'reference': forms.TextInput(attrs={'class': 'form-input'}),
        }

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount <= 0:
            raise forms.ValidationError('Amount must be greater than zero.')
        return amount


class MemberFineForm(forms.ModelForm):
    class Meta:
        model = MemberFine
        fields = ['membership', 'category', 'description', 'amount', 'due_date']
        widgets = {
            'membership': forms.Select(attrs={'class': 'form-input'}),
            'category': forms.Select(attrs={'class': 'form-input'}),
            'description': forms.TextInput(attrs={'class': 'form-input'}),
            'amount': forms.NumberInput(attrs={'class': 'form-input', 'min': '0.01', 'step': '0.01'}),
            'due_date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
        }

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount <= 0:
            raise forms.ValidationError('Fine amount must be greater than zero.')
        return amount


class FinePaymentForm(forms.ModelForm):
    class Meta:
        model = FinePayment
        fields = ['fine', 'amount', 'payment_method', 'reference']
        widgets = {
            'fine': forms.Select(attrs={'class': 'form-input'}),
            'amount': forms.NumberInput(attrs={'class': 'form-input', 'min': '0.01', 'step': '0.01'}),
            'payment_method': forms.Select(attrs={'class': 'form-input'}),
            'reference': forms.TextInput(attrs={'class': 'form-input'}),
        }

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount <= 0:
            raise forms.ValidationError('Payment amount must be greater than zero.')
        return amount


class SavingsGoalForm(forms.ModelForm):
    class Meta:
        model = SavingsGoal
        fields = ['title', 'description', 'target_amount', 'target_date']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. School fees fund'}),
            'description': forms.Textarea(attrs={'class': 'form-input', 'rows': 3, 'placeholder': 'What is the group saving for?'}),
            'target_amount': forms.NumberInput(attrs={'class': 'form-input', 'min': '1', 'step': '0.01'}),
            'target_date': forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
        }

    def clean_target_amount(self):
        amount = self.cleaned_data['target_amount']
        if amount <= 0:
            raise forms.ValidationError('The goal target must be greater than zero.')
        return amount


class GoalProgressForm(forms.ModelForm):
    class Meta:
        model = GoalProgressEntry
        fields = ['amount', 'note']
        widgets = {
            'amount': forms.NumberInput(attrs={'class': 'form-input', 'min': '0.01', 'step': '0.01'}),
            'note': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Optional milestone note'}),
        }

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount <= 0:
            raise forms.ValidationError('Enter an amount greater than zero.')
        return amount


class ChamaMeetingForm(forms.ModelForm):
    meeting_date = forms.DateTimeField(
        input_formats=['%Y-%m-%dT%H:%M'],
        widget=forms.DateTimeInput(
            attrs={'class': 'form-input', 'type': 'datetime-local'},
            format='%Y-%m-%dT%H:%M',
        ),
    )

    class Meta:
        model = ChamaMeeting
        fields = ['title', 'meeting_date', 'location', 'agenda']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. Monthly chama meeting'}),
            'location': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Meeting location or online link'}),
            'agenda': forms.Textarea(attrs={'class': 'form-input', 'rows': 3, 'placeholder': 'Topics for discussion'}),
        }


class MeetingMinutesForm(forms.ModelForm):
    class Meta:
        model = ChamaMeeting
        fields = ['minutes']
        widgets = {
            'minutes': forms.Textarea(attrs={'class': 'form-input', 'rows': 3, 'placeholder': 'Decisions, actions and follow-ups'}),
        }


class MeetingAttendanceForm(forms.ModelForm):
    class Meta:
        model = MeetingAttendance
        fields = ['membership', 'status']
        widgets = {
            'membership': forms.Select(attrs={'class': 'form-input'}),
            'status': forms.Select(attrs={'class': 'form-input'}),
        }


class PlanInquiryForm(forms.ModelForm):
    class Meta:
        model = PlanInquiry
        fields = ['contact_phone', 'contact_email', 'message']
        widgets = {
            'contact_phone': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Best number to reach you'}),
            'contact_email': forms.EmailInput(attrs={'class': 'form-input', 'placeholder': 'Email (optional)'}),
            'message': forms.Textarea(attrs={'class': 'form-input', 'rows': 3, 'placeholder': 'Tell us what your chama needs'}),
        }
