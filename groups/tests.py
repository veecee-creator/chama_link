import os
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Chama, Membership
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
