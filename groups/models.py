
from django.db import models
from django.contrib.auth.models import User


class Chama(models.Model):
    SAVINGS_MODELS = [
        ('POOLED', 'Pooled savings and lending'),
        ('MERRY_GO_ROUND', 'Merry-go-round'),
    ]
    CONTRIBUTION_FREQUENCIES = [
        ('WEEKLY', 'Weekly'),
        ('MONTHLY', 'Monthly'),
    ]
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_chamas',
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    meeting_location = models.CharField(max_length=150, blank=True)
    contribution_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )
    savings_model = models.CharField(max_length=20, choices=SAVINGS_MODELS, default='POOLED')
    contribution_frequency = models.CharField(
        max_length=10, choices=CONTRIBUTION_FREQUENCIES, default='MONTHLY'
    )
    contribution_due_day = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Membership(models.Model):
    ROLE_CHOICES = [
        ('CHAIRPERSON', 'Chairperson'),
        ('TREASURER', 'Treasurer'),
        ('SECRETARY', 'Secretary'),
        ('MEMBER', 'Member'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='chama_memberships'
    )

    chama = models.ForeignKey(
        Chama,
        on_delete=models.CASCADE,
        related_name='memberships'
    )
    full_name = models.CharField(max_length=100)
    phone_number = models.CharField(max_length=15)
    national_id = models.CharField(max_length=20, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='MEMBER'
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('chama', 'national_id'),
                condition=models.Q(national_id__isnull=False),
                name='unique_national_id_per_chama',
            ),
            models.UniqueConstraint(
                fields=('chama', 'phone_number'),
                name='unique_phone_per_chama',
            ),
        ]

    def __str__(self):
        return f"{self.full_name} - {self.chama.name}"


class Contribution(models.Model):
    PAYMENT_METHODS = [
        ('MPESA', 'M-Pesa'),
        ('CASH', 'Cash'),
        ('BANK', 'Bank Transfer'),
    ]

    membership = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        related_name='contributions'
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )
    payment_method = models.CharField(
        max_length=10,
        choices=PAYMENT_METHODS,
        default='MPESA'
    )
    reference = models.CharField(
        max_length=100,
        blank=True
    )
    contribution_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.membership.full_name} - KSh {self.amount}"


class Loan(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending Approval'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('REPAID', 'Fully Repaid'),
    ]

    membership = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        related_name='loans'
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )
    purpose = models.TextField()
    interest_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='PENDING'
    )
    applied_at = models.DateTimeField(auto_now_add=True)
    due_date = models.DateField(null=True, blank=True)

    @property
    def total_repaid(self):
        return self.repayments.aggregate(
            total=models.Sum('amount')
        )['total'] or 0

    @property
    def outstanding_balance(self):
        total_due = self.amount + (
            self.amount * self.interest_rate / 100
        )
        return max(total_due - self.total_repaid, 0)

    def __str__(self):
        return f"{self.membership.full_name} - KSh {self.amount}"


class LoanRepayment(models.Model):
    PAYMENT_METHODS = [
        ('MPESA', 'M-Pesa'),
        ('CASH', 'Cash'),
        ('BANK', 'Bank Transfer'),
    ]

    loan = models.ForeignKey(
        Loan,
        on_delete=models.PROTECT,
        related_name='repayments'
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )
    payment_method = models.CharField(
        max_length=10,
        choices=PAYMENT_METHODS,
        default='MPESA'
    )
    reference = models.CharField(
        max_length=100,
        blank=True
    )
    payment_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Loan repayment - KSh {self.amount}"


class FinancialActivity(models.Model):
    """Append-only audit entry for financial actions within a chama."""
    chama = models.ForeignKey(
        Chama, on_delete=models.CASCADE, related_name='financial_activities'
    )
    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='chama_financial_activities'
    )
    action = models.CharField(max_length=40)
    description = models.CharField(max_length=255)
    record_type = models.CharField(max_length=40, blank=True)
    record_id = models.PositiveBigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'financial activities'

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValueError('Financial activity records cannot be changed.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('Financial activity records cannot be deleted.')

    def __str__(self):
        return f'{self.action}: {self.description}'


class ChamaCashflowEntry(models.Model):
    TYPES = [('INCOME', 'Other income'), ('EXPENSE', 'Expense')]
    chama = models.ForeignKey(Chama, on_delete=models.CASCADE, related_name='cashflow_entries')
    entry_type = models.CharField(max_length=10, choices=TYPES)
    category = models.CharField(max_length=80)
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    entry_date = models.DateField()
    reference = models.CharField(max_length=100, blank=True)
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-entry_date', '-created_at']

    def __str__(self):
        return f'{self.get_entry_type_display()} · KSh {self.amount} · {self.chama.name}'


class MemberFine(models.Model):
    CATEGORIES = [
        ('LATE_CONTRIBUTION', 'Late contribution'),
        ('ABSENCE', 'Missed meeting'),
        ('OTHER', 'Other'),
    ]
    membership = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name='fines')
    category = models.CharField(max_length=24, choices=CATEGORIES, default='OTHER')
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    due_date = models.DateField(null=True, blank=True)
    issued_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='issued_member_fines')
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-issued_at']

    @property
    def total_paid(self):
        return self.payments.aggregate(total=models.Sum('amount'))['total'] or 0

    @property
    def balance(self):
        return max(self.amount - self.total_paid, 0)

    @property
    def status(self):
        return 'PAID' if self.balance <= 0 else 'OPEN'

    def __str__(self):
        return f'{self.membership.full_name} · {self.get_category_display()} · KSh {self.balance} due'


class FinePayment(models.Model):
    fine = models.ForeignKey(MemberFine, on_delete=models.PROTECT, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=10, choices=Contribution.PAYMENT_METHODS, default='MPESA')
    reference = models.CharField(max_length=100, blank=True)
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    paid_at = models.DateTimeField(auto_now_add=True)


class RotationPayout(models.Model):
    STATUS_CHOICES = [('PENDING', 'Upcoming'), ('PAID', 'Paid out')]
    chama = models.ForeignKey(Chama, on_delete=models.CASCADE, related_name='rotation_payouts')
    turn_number = models.PositiveSmallIntegerField()
    recipient = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name='rotation_payouts')
    scheduled_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    paid_at = models.DateTimeField(null=True, blank=True)
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['turn_number']
        constraints = [models.UniqueConstraint(fields=('chama', 'turn_number'), name='unique_rotation_turn_per_chama')]


class MpesaTransaction(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SUCCESS = "SUCCESS", "Successful"
        FAILED = "FAILED", "Failed"

    class Type(models.TextChoices):
        CONTRIBUTION = "contribution", "Contribution"
        LOAN_REPAYMENT = "loan_repayment", "Loan repayment"

    # Assumed names: "Membership" and "Loan". Change to match your models.
    membership = models.ForeignKey(
        "Membership", on_delete=models.PROTECT, related_name="mpesa_transactions"
    )
    loan = models.ForeignKey(
        "Loan", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="mpesa_transactions",
    )
    transaction_type = models.CharField(max_length=20, choices=Type.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    phone_number = models.CharField(max_length=15)

    merchant_request_id = models.CharField(max_length=100, blank=True)
    checkout_request_id = models.CharField(
    max_length=100,
    unique=True,
    null=True,
    blank=True
)

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    receipt_number = models.CharField(max_length=30, blank=True, db_index=True)
    result_code = models.IntegerField(null=True, blank=True)
    result_desc = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.checkout_request_id} · {self.status} · KSh {self.amount}"
