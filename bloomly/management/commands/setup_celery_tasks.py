from django.core.management.base import BaseCommand
from django_celery_beat.models import CrontabSchedule, PeriodicTask


class Command(BaseCommand):
    help = 'Tworzy zadania cykliczne dla Celery Beat'

    def handle(self, *args, **options):
        self.stdout.write('Tworzenie zadań cyklicznych...')

        # Usuń istniejące zadania Bloomly (jeśli są)
        deleted_tasks = PeriodicTask.objects.filter(name__icontains='Bloomly').delete()
        if deleted_tasks[0] > 0:
            self.stdout.write(f'Usunięto {deleted_tasks[0]} starych zadań')

        # Zadanie 1: Sprawdzaj przypomnienia co godzinę
        schedule_hourly, _ = CrontabSchedule.objects.get_or_create(
            minute='0',
            hour='*',
            day_of_week='*',
            day_of_month='*',
            month_of_year='*',
        )

        PeriodicTask.objects.get_or_create(
            name='Bloomly - Sprawdź przypomnienia co godzinę',
            defaults={
                'crontab': schedule_hourly,
                'task': 'bloomly.tasks.sprawdz_przypomnienia',
                'enabled': True,
            }
        )
        self.stdout.write('✓ Zadanie sprawdzania przypomnień (co godzinę)')

        # Zadanie 2: Generuj przypomnienia codziennie o 8:00
        schedule_daily, _ = CrontabSchedule.objects.get_or_create(
            minute='0',
            hour='8',
            day_of_week='*',
            day_of_month='*',
            month_of_year='*',
        )

        PeriodicTask.objects.get_or_create(
            name='Bloomly - Generuj przypomnienia codziennie',
            defaults={
                'crontab': schedule_daily,
                'task': 'bloomly.tasks.generuj_przypomnienia_dla_wszystkich',
                'enabled': True,
            }
        )
        self.stdout.write('✓ Zadanie generowania przypomnień (8:00 rano)')

        # NOWE Zadanie 3: Analizuj rośliny codziennie o 2:00
        schedule_night, _ = CrontabSchedule.objects.get_or_create(
            minute='0',
            hour='2',
            day_of_week='*',
            day_of_month='*',
            month_of_year='*',
        )

        PeriodicTask.objects.get_or_create(
            name='Bloomly - Analizuj rośliny ML',
            defaults={
                'crontab': schedule_night,
                'task': 'bloomly.tasks.analizuj_wszystkie_rosliny',
                'enabled': True,
            }
        )
        self.stdout.write('✓ Zadanie analizy ML (2:00 w nocy)')

        # NOWE Zadanie 4: Zastosuj rekomendacje ML w niedziele o 3:00
        schedule_weekly, _ = CrontabSchedule.objects.get_or_create(
            minute='0',
            hour='3',
            day_of_week='0',  # Niedziela
            day_of_month='*',
            month_of_year='*',
        )

        PeriodicTask.objects.get_or_create(
            name='Bloomly - Zastosuj rekomendacje ML',
            defaults={
                'crontab': schedule_weekly,
                'task': 'bloomly.tasks.zastosuj_rekomendacje_automatycznie',
                'enabled': True,
            }
        )
        self.stdout.write('✓ Zadanie automatycznego stosowania rekomendacji (niedziela 3:00)')

        self.stdout.write(
            self.style.SUCCESS('\n🎉 Wszystkie zadania cykliczne zostały skonfigurowane!')
        )

        self.stdout.write('\nUtworzono zadania:')
        self.stdout.write('• Co godzinę: sprawdzanie przypomnień do wysłania')
        self.stdout.write('• Codziennie 8:00: generowanie nowych przypomnień')
        self.stdout.write('• Codziennie 2:00: analiza ML wszystkich roślin')
        self.stdout.write('• Niedziela 3:00: automatyczne stosowanie rekomendacji ML')
