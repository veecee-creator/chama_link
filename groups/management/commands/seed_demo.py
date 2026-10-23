"""Create fictional ChamaLink demo records on an empty demo database."""

import os
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from groups.models import (
    Chama,
    ChamaCashflowEntry,
    Contribution,
    FinancialActivity,
    FinePayment,
    Loan,
    LoanRepayment,
    MemberFine,
    Membership,
    RotationPayout,
    SavingsGoal,
    GoalProgressEntry,
    ChamaMeeting,
    MeetingAttendance,
)


class Command(BaseCommand):
    help = "Seed a fictional sample chama for a public demo environment."

    @transaction.atomic
    def handle(self, *args, **options):
        if os.getenv("CHAMALINK_DEMO_MODE", "").lower() != "true":
            raise CommandError("Set CHAMALINK_DEMO_MODE=true to seed demo data.")

        username = os.getenv("DEMO_USERNAME", "").strip()
        password = os.getenv("DEMO_PASSWORD", "")
        if not username or len(password) < 14:
            raise CommandError(
                "Set DEMO_USERNAME and a DEMO_PASSWORD with at least 14 characters."
            )

        demo_user, user_created = User.objects.get_or_create(
            username=username,
            defaults={"email": "demo@example.invalid", "is_active": True},
        )
        if user_created:
            demo_user.set_password(password)
            demo_user.save(update_fields=["password"])

        chama, _ = Chama.objects.get_or_create(
            name="Tumaini Community Savings",
            defaults={
                "created_by": demo_user,
                "description": "Fictional sample group for exploring ChamaLink.",
                "meeting_location": "Demo location",
                "contribution_amount": Decimal("500.00"),
                "savings_model": "MERRY_GO_ROUND",
                "contribution_frequency": "MONTHLY",
                "contribution_due_day": 5,
                "plan": "PLUS",
            },
        )
        if chama.plan != "PLUS" or chama.premium_until is not None:
            chama.plan = "PLUS"
            chama.premium_until = None
            chama.save(update_fields=["plan", "premium_until"])

        sample_members = [
            ("Amina Demo", "0700000001", "CHAIRPERSON", demo_user),
            ("Baraka Sample", "0700000002", "TREASURER", None),
            ("Zuri Example", "0700000003", "SECRETARY", None),
            ("Kito Sample", "0700000004", "MEMBER", None),
        ]
        members = []
        for name, phone, role, user in sample_members:
            member, _ = Membership.objects.get_or_create(
                chama=chama,
                phone_number=phone,
                defaults={
                    "full_name": name,
                    "role": role,
                    "user": user,
                    "national_id": None,
                    "is_active": True,
                },
            )
            members.append(member)

        for index, member in enumerate(members, start=1):
            Contribution.objects.get_or_create(
                membership=member,
                reference=f"DEMO-CONTRIBUTION-{index}",
                defaults={
                    "amount": Decimal("500.00") * index,
                    "payment_method": "CASH",
                },
            )

        loan, _ = Loan.objects.get_or_create(
            membership=members[1],
            purpose="DEMO: School fees support",
            defaults={
                "amount": Decimal("8000.00"),
                "interest_rate": Decimal("5.00"),
                "status": "APPROVED",
                "due_date": timezone.localdate() + timedelta(days=30),
            },
        )
        LoanRepayment.objects.get_or_create(
            loan=loan,
            reference="DEMO-REPAYMENT-1",
            defaults={
                "amount": Decimal("2000.00"),
                "payment_method": "CASH",
            },
        )

        fine, _ = MemberFine.objects.get_or_create(
            membership=members[3],
            description="DEMO: Missed group meeting",
            defaults={
                "category": "ABSENCE",
                "amount": Decimal("200.00"),
                "due_date": timezone.localdate() + timedelta(days=14),
                "issued_by": demo_user,
            },
        )
        FinePayment.objects.get_or_create(
            fine=fine,
            reference="DEMO-FINE-PAYMENT-1",
            defaults={
                "amount": Decimal("100.00"),
                "payment_method": "CASH",
                "recorded_by": demo_user,
            },
        )

        for index, member in enumerate(members, start=1):
            RotationPayout.objects.get_or_create(
                chama=chama,
                turn_number=index,
                defaults={
                    "recipient": member,
                    "scheduled_date": timezone.localdate() + timedelta(days=30 * index),
                    "amount": chama.contribution_amount * len(members),
                },
            )

        goal, _ = SavingsGoal.objects.get_or_create(
            chama=chama,
            title="School fees fund",
            defaults={
                "description": "A shared plan to support members' school costs.",
                "target_amount": Decimal("120000.00"),
                "target_date": timezone.localdate() + timedelta(days=90),
                "created_by": demo_user,
            },
        )
        GoalProgressEntry.objects.get_or_create(
            goal=goal,
            note="Starting milestone",
            defaults={"amount": Decimal("32500.00"), "recorded_by": demo_user},
        )

        meeting, _ = ChamaMeeting.objects.get_or_create(
            chama=chama,
            title="Monthly chama check-in",
            defaults={
                "meeting_date": timezone.now() - timedelta(days=7),
                "location": "Demo meeting room",
                "agenda": "Review contributions, upcoming loans and the group goal.",
                "minutes": "Members agreed to keep monthly contributions on schedule.",
                "created_by": demo_user,
            },
        )
        for member in members:
            MeetingAttendance.objects.get_or_create(
                meeting=meeting,
                membership=member,
                defaults={"status": "PRESENT", "recorded_by": demo_user},
            )

        for entry_type, category, description, amount in [
            ("INCOME", "Other income", "DEMO: Fundraising proceeds", Decimal("1200.00")),
            ("EXPENSE", "Meeting expense", "DEMO: Venue and refreshments", Decimal("750.00")),
        ]:
            ChamaCashflowEntry.objects.get_or_create(
                chama=chama,
                entry_type=entry_type,
                description=description,
                defaults={
                    "category": category,
                    "amount": amount,
                    "entry_date": timezone.localdate(),
                    "recorded_by": demo_user,
                },
            )

        FinancialActivity.objects.get_or_create(
            chama=chama,
            action="Demo data initialized",
            description="Fictional sample records created for the ChamaLink demo.",
        )
        self.stdout.write(self.style.SUCCESS("Fictional ChamaLink demo data is ready."))
