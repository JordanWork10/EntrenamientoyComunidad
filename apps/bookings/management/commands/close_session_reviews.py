from django.core.management.base import BaseCommand

from apps.bookings.session_review_services import close_overdue_reviews


class Command(BaseCommand):
    help = (
        'Cierra confirmaciones de sesiones tras su plazo, '
        'sin fingir conformidad.'
    )

    def handle(self, *args, **options):
        count = close_overdue_reviews()

        self.stdout.write(
            self.style.SUCCESS(
                f'Confirmaciones sin respuesta cerradas: {count}'
            )
        )