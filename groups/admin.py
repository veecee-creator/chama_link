
from django.contrib import admin
from .models import (
    Chama, Membership, Contribution, SavingsGoal, GoalProgressEntry,
    ChamaMeeting, MeetingAttendance, PlanInquiry,
)


@admin.register(Chama)
class ChamaAdmin(admin.ModelAdmin):
    list_display = ('name', 'plan', 'premium_until', 'created_at')
    list_filter = ('plan',)
    search_fields = ('name',)


admin.site.register(Membership)
admin.site.register(Contribution)
admin.site.register(SavingsGoal)
admin.site.register(GoalProgressEntry)
admin.site.register(ChamaMeeting)
admin.site.register(MeetingAttendance)


@admin.register(PlanInquiry)
class PlanInquiryAdmin(admin.ModelAdmin):
    list_display = ('chama', 'contact_phone', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('chama__name', 'contact_phone', 'contact_email')
    readonly_fields = ('created_at',)

from .models import MpesaTransaction



@admin.register(MpesaTransaction)
class MpesaTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "membership",
        "transaction_type",
        "amount",
        "phone_number",
        "status",
        "receipt_number",
        "created_at",
    )

    list_filter = ("status", "transaction_type", "created_at")

    search_fields = (
        "phone_number",
        "checkout_request_id",
        "receipt_number",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )
