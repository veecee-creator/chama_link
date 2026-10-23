
from django.urls import path
from . import views

urlpatterns = [
    path('service-worker.js', views.service_worker, name='service_worker'),
    path('', views.landing, name='landing'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('chamas/', views.chama_directory, name='chama_directory'),
    path('chamas/<int:chama_id>/join/', views.join_chama, name='join_chama'),
    path('members/<int:member_id>/invite/', views.issue_member_invite, name='issue_member_invite'),
    path('settings/', views.app_settings, name='app_settings'),
    path('plans/', views.plans, name='plans'),
    path('savings-goals/', views.savings_goals, name='savings_goals'),
    path('meetings/', views.meetings, name='meetings'),

    path('members/', views.members, name='members'),

    path(
        'members/register/',
        views.register_member,
        name='register_member'
    ),

    path(
        'chamas/create/',
        views.create_chama,
        name='create_chama'
    ),

    path(
        'contributions/',
        views.contributions,
        name='contributions'
    ),

    path(
        'contributions/record/',
        views.record_contribution,
        name='record_contribution'
    ),

    path(
        'members/<int:member_id>/edit/',
        views.edit_member,
        name='edit_member'
    ),

    path(
        'members/<int:member_id>/delete/',
        views.delete_member,
        name='delete_member'
    ),

    path('loans/', views.loans, name='loans'),

    path(
        'loans/apply/',
        views.apply_for_loan,
        name='apply_for_loan'
    ),

    path(
        'loans/repay/',
        views.record_loan_repayment,
        name='record_loan_repayment'
    ),

    path(
        'financial-reports/',
        views.financial_reports,
        name='financial_reports'
    ),

    path('group-finances/', views.group_finances, name='group_finances'),

    path(
        'member-financial-history/<int:membership_id>/',
        views.member_financial_history,
        name='member_financial_history'
    ),

    # M-Pesa payment page
    path(
        'mpesa/payment/',
        views.mpesa_payment_page,
        name='mpesa_payment_page'
    ),

    # Initiate M-Pesa STK Push
    path(
        'mpesa/pay/',
        views.initiate_mpesa_payment,
        name='initiate_mpesa_payment'
    ),

    # Receive M-Pesa callback
    path(
        'mpesa/callback/',
        views.mpesa_callback,
        name='mpesa_callback'
    ),
]
