
from django.db import models


class Member(models.Model):
    full_name = models.CharField(max_length=100)
    phone_number = models.CharField(max_length=15, unique=True)
    national_id = models.CharField(max_length=20, unique=True)
    date_joined = models.DateField(auto_now_add=True)

    def __str__(self):
        return self.full_name
    