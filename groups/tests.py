import os
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import (
    Chama, Membership, SavingsGoal, GoalProgressEntry, ChamaMeeting,
    MeetingAttendance, PlanInquiry,
)
from .views import is_chama_role


class DemoFeatureAccessTests(TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            'CHAMALINK_DEMO_MODE': 'true',
            'DEMO_USERNAME': 'demo-tester',
        })
        self.env.start()
        self.addCleanup(self.env.stop)

        self.demo_user = User.objects.create_user('demo-tester', password='test-password')
        self.member_user = User.objects.create_user('regular-member', password='test-password')
        self.chama = Chama.objects.create(
            name='Sample Chama', contribution_amount='500.00',
            created_by=self.demo_user,
        )
        Membership.objects.create(
            user=self.demo_user, chama=self.chama, full_name='Demo Tester',
            phone_number='0700000001', role='CHAIRPERSON',
        )
        Membership.objects.create(
            user=self.member_user, chama=self.chama, full_name='Regular Member',
            phone_number='0700000002', role='MEMBER',
        )

    def test_demo_login_can_exercise_all_chama_roles(self):
        for role in ('CHAIRPERSON', 'TREASURER', 'SECRETARY'):
            with self.subTest(role=role):
                self.assertTrue(is_chama_role(self.demo_user, self.chama, role))

    def test_regular_member_keeps_role_restrictions(self):
        self.assertFalse(is_chama_role(self.member_user, self.chama, 'TREASURER'))
        self.assertTrue(is_chama_role(self.member_user, self.chama, 'MEMBER'))

    def test_demo_dashboard_links_to_finance_and_payment_features(self):
        self.client.force_login(self.demo_user)
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('group_finances'))
        self.assertContains(response, reverse('mpesa_payment_page'))


class GroupGrowthFeatureTests(TestCase):
    def setUp(self):
        self.chair = User.objects.create_user('group-chair', password='test-password')
        self.member_user = User.objects.create_user('group-member', password='test-password')
        self.chama = Chama.objects.create(
            name='Tumaini Group', contribution_amount='500.00', plan='PLUS',
            created_by=self.chair,
        )
        self.chair_membership = Membership.objects.create(
            user=self.chair, chama=self.chama, full_name='Group Chair',
            phone_number='0711000001', role='CHAIRPERSON',
        )
        self.member = Membership.objects.create(
            user=self.member_user, chama=self.chama, full_name='Group Member',
            phone_number='0711000002', role='MEMBER',
        )

    def test_chair_can_create_goal_and_track_progress_without_a_contribution(self):
        self.client.force_login(self.chair)
        response = self.client.post(reverse('savings_goals'), {
            'action': 'create_goal', 'title': 'School fees',
            'description': 'Plan for next term', 'target_amount': '120000.00',
            'target_date': '',
        })
        self.assertRedirects(response, reverse('savings_goals'))
        goal = SavingsGoal.objects.get(chama=self.chama, title='School fees')

        response = self.client.post(reverse('savings_goals'), {
            'action': 'record_progress', 'goal_id': goal.pk,
            'amount': '15000.00', 'note': 'First milestone',
        })
        self.assertRedirects(response, reverse('savings_goals'))
        self.assertEqual(goal.tracked_amount, 15000)
        self.assertEqual(GoalProgressEntry.objects.filter(goal=goal).count(), 1)

    def test_member_cannot_post_group_goal_updates(self):
        self.client.force_login(self.member_user)
        self.client.raise_request_exception = False
        response = self.client.post(reverse('savings_goals'), {
            'action': 'create_goal', 'title': 'Not allowed',
            'target_amount': '1000.00',
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(SavingsGoal.objects.filter(chama=self.chama).exists())

    def test_free_group_can_read_plans_but_cannot_create_plus_features(self):
        self.chama.plan = 'FREE'
        self.chama.save(update_fields=['plan'])
        self.client.force_login(self.chair)
        response = self.client.get(reverse('savings_goals'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('plans'))

        response = self.client.post(reverse('savings_goals'), {
            'action': 'create_goal', 'title': 'Upgrade needed',
            'target_amount': '5000.00',
        })
        self.assertRedirects(response, reverse('plans'))
        self.assertFalse(SavingsGoal.objects.filter(chama=self.chama).exists())

    def test_chair_can_schedule_meeting_and_record_attendance(self):
        self.client.force_login(self.chair)
        response = self.client.post(reverse('meetings'), {
            'action': 'create_meeting', 'title': 'Monthly meeting',
            'meeting_date': '2026-10-30T15:00', 'location': 'Community hall',
            'agenda': 'Review contributions and next steps',
        })
        self.assertRedirects(response, reverse('meetings'))
        meeting = ChamaMeeting.objects.get(chama=self.chama, title='Monthly meeting')

        response = self.client.post(reverse('meetings'), {
            'action': 'record_attendance', 'meeting_id': meeting.pk,
            'membership': self.member.pk, 'status': 'PRESENT',
        })
        self.assertRedirects(response, reverse('meetings'))
        self.assertTrue(MeetingAttendance.objects.filter(
            meeting=meeting, membership=self.member, status='PRESENT'
        ).exists())

    def test_officer_can_request_a_plan_quote(self):
        self.client.force_login(self.chair)
        response = self.client.post(reverse('plans'), {
            'contact_phone': '0711000001', 'contact_email': 'chair@example.com',
            'message': 'We would like help setting up goals and meetings.',
        })
        self.assertRedirects(response, reverse('plans'))
        self.assertTrue(PlanInquiry.objects.filter(
            chama=self.chama, requested_by=self.chair, status='NEW'
        ).exists())

    def test_plans_are_publicly_viewable(self):
        response = self.client.get(reverse('plans'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ChamaLink Plus')

    def test_member_can_claim_registration_with_formatted_national_id(self):
        unclaimed = Membership.objects.create(
            chama=self.chama, full_name='New Member', phone_number='0711000003',
            national_id='0012-3456', role='MEMBER',
        )
        new_user = User.objects.create_user('new-member', password='test-password')
        self.client.force_login(new_user)

        response = self.client.post(reverse('join_chama', args=[self.chama.pk]), {
            'national_id': ' 0012 3456 ',
        })

        self.assertRedirects(response, reverse('dashboard'))
        unclaimed.refresh_from_db()
        self.assertEqual(unclaimed.user, new_user)
        self.assertEqual(self.client.session['active_chama_id'], self.chama.pk)

    def test_chairperson_invite_link_opens_and_claims_the_registered_member(self):
        unclaimed = Membership.objects.create(
            chama=self.chama, full_name='Invited Member', phone_number='0711000004',
            role='MEMBER',
        )
        self.client.force_login(self.chair)
        response = self.client.post(reverse('issue_member_invite', args=[unclaimed.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('members'))
        self.assertIn('member_invite_url', self.client.session)

        members_response = self.client.get(reverse('members'))
        invite_url = members_response.context['invite_url']
        parsed_invite = urlsplit(invite_url)
        self.assertIn('invite=', parsed_invite.query, invite_url)
        token = parse_qs(parsed_invite.query)['invite'][0]
        self.assertEqual(parsed_invite.path, reverse('join_chama', args=[self.chama.pk]))

        new_user = User.objects.create_user('invited-member', password='test-password')
        self.client.force_login(new_user)
        invite_path = f'{parsed_invite.path}?invite={token}'
        self.assertEqual(self.client.get(invite_path).status_code, 200)
        response = self.client.post(invite_path, {'invite': token})

        self.assertRedirects(response, reverse('dashboard'))
        unclaimed.refresh_from_db()
        self.assertEqual(unclaimed.user, new_user)


class AppPageReachabilityTests(TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'CHAMALINK_DEMO_MODE': 'true'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.user = User.objects.create_superuser(
            username='page-check', email='pages@example.com', password='test-password'
        )
        self.chama = Chama.objects.create(
            name='Page Check Chama', contribution_amount='500.00', plan='PLUS',
            created_by=self.user,
        )
        self.member = Membership.objects.create(
            user=self.user, chama=self.chama, full_name='Page Check Member',
            phone_number='0711000099', role='CHAIRPERSON',
        )
        self.client.force_login(self.user)

    def test_public_entry_and_authenticated_pages_render(self):
        self.client.logout()
        for url_name in ('landing', 'login', 'register', 'plans'):
            with self.subTest(page=url_name):
                self.assertEqual(self.client.get(reverse(url_name)).status_code, 200)

        self.client.force_login(self.user)
        pages = [
            ('dashboard', ()), ('chama_directory', ()),
            ('join_chama', (self.chama.pk,)), ('app_settings', ()),
            ('plans', ()), ('savings_goals', ()), ('meetings', ()),
            ('members', ()), ('register_member', ()), ('create_chama', ()),
            ('contributions', ()), ('record_contribution', ()),
            ('edit_member', (self.member.pk,)), ('delete_member', (self.member.pk,)),
            ('loans', ()), ('apply_for_loan', ()), ('record_loan_repayment', ()),
            ('financial_reports', ()), ('group_finances', ()),
            ('member_financial_history', (self.member.pk,)),
            ('mpesa_payment_page', ()),
        ]
        for url_name, args in pages:
            with self.subTest(page=url_name):
                response = self.client.get(reverse(url_name, args=args))
                self.assertEqual(response.status_code, 200)
