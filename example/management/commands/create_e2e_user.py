from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

E2E_USERNAME = "e2e"
E2E_PASSWORD = "e2e-secret"


class Command(BaseCommand):
    help = "Create the e2e test user (idempotent)"

    def handle(self, *args, **options):
        User = get_user_model()
        user, created = User.objects.get_or_create(username=E2E_USERNAME)
        if created:
            user.set_password(E2E_PASSWORD)
            user.save()
            self.stdout.write(f"Created user '{E2E_USERNAME}'")
        else:
            self.stdout.write(f"User '{E2E_USERNAME}' already exists")
