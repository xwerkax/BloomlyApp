# bloomly/management/commands/trenuj_modele.py
from django.core.management.base import BaseCommand
from bloomly.ml_utils import retrenuj_wszystkie_modele
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Trenuje modele ML dla wszystkich roślin'

    def handle(self, *args, **options):
        self.stdout.write('🤖 Trenowanie modeli ML...\n')

        wynik = retrenuj_wszystkie_modele()

        self.stdout.write('\n' + '=' * 50)
        self.stdout.write(
            self.style.SUCCESS(
                f'✓ Wytrenowano: {wynik["wytrenowane"]} modeli'
            )
        )
        self.stdout.write(f'⚠ Pominięto: {wynik["pominiete"]} (za mało danych)')

        if wynik['bledy'] > 0:
            self.stdout.write(
                self.style.ERROR(f'✗ Błędy: {wynik["bledy"]}')
            )

        self.stdout.write('=' * 50)

