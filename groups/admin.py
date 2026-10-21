
from django.contrib import admin
from .models import Chama, Membership, Contribution
admin.site.register(Chama)
admin.site.register(Membership)
admin.site.register(Contribution)

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
