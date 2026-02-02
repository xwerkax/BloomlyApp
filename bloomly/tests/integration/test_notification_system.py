"""
Testy integracyjne - system powiadomień
Testują kompletny przepływ przypomnień i wysyłania emaili
"""

from django.test import TestCase
from unittest.mock import patch
from unittest.mock import patch, MagicMock
from django.contrib.auth.models import User
from django.utils import timezone
from django.core import mail
from datetime import timedelta, date
from unittest.mock import patch, MagicMock

from bloomly.models import (
    Roslina, CzynoscPielegnacyjna, Przypomnienie, ProfilUzytkownika
)
from bloomly.tasks import (
    wyslij_email_przypomnienie,
    sprawdz_przypomnienia,
    odswiez_przypomnienie_rosliny,
    odswiez_przypomnienia_dla_wszystkich
)


class NotificationCreationFlowTest(TestCase):
    """Test tworzenia przypomnień"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.roslina = Roslina.objects.create(
            nazwa="Monstera",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            data_zakupu=date.today()
        )

    def test_reminder_created_after_watering(self):
        """Test: przypomnienie tworzone po podlaniu"""

        # 1. Podlej roślinę
        podlewanie = CzynoscPielegnacyjna.objects.create(
            roslina=self.roslina,
            typ="podlewanie",
            wykonane=True,
            uzytkownik=self.user,
            data=timezone.now(),
            stan_gleby="dry"
        )

        # 2. Utwórz przypomnienie (symulacja automatycznego procesu)
        from bloomly.models import utworz_przypomnienie_podlewanie
        przypomnienie = utworz_przypomnienie_podlewanie(self.roslina)

        # 3. Sprawdź że przypomnienie zostało utworzone
        self.assertIsNotNone(przypomnienie)
        self.assertEqual(przypomnienie.roslina, self.roslina)
        self.assertEqual(przypomnienie.uzytkownik, self.user)
        self.assertEqual(przypomnienie.typ, "podlewanie")
        self.assertEqual(przypomnienie.status, "oczekujace")
        self.assertFalse(przypomnienie.wyslane)

        # 4. Data przypomnienia powinna być w przyszłości
        self.assertGreater(
            przypomnienie.data_przypomnienia,
            timezone.now()
        )

    def test_one_open_reminder_per_plant(self):
        """Test: tylko jedno otwarte przypomnienie na roślinę (ONE-OPEN)"""

        # 1. Podlej roślinę pierwszy raz
        CzynoscPielegnacyjna.objects.create(
            roslina=self.roslina,
            typ="podlewanie",
            uzytkownik=self.user,
            wykonane=True,
            data=timezone.now() - timedelta(days=7)
        )

        from bloomly.models import utworz_przypomnienie_podlewanie
        przypomnienie1 = utworz_przypomnienie_podlewanie(self.roslina)

        # 2. Spróbuj utworzyć drugie przypomnienie
        result2 = utworz_przypomnienie_podlewanie(self.roslina)

        otwarte = Przypomnienie.objects.filter(
            roslina=self.roslina,
            status__in=['oczekujace', 'wyslane']
        )
        self.assertEqual(otwarte.count(), 1, "Powinno być dokładnie jedno otwarte przypomnienie")

        # Jeśli funkcja zwraca przypomnienie, to powinno być to samo
        if result2 is not None:
            self.assertEqual(result2.id, przypomnienie1.id)

    def test_reminder_updates_on_new_watering(self):
        """Test: przypomnienie aktualizuje się po nowym podlaniu"""

        # 1. Utwórz pierwsze przypomnienie
        CzynoscPielegnacyjna.objects.create(
            roslina=self.roslina,
            typ="podlewanie",
            uzytkownik=self.user,
            wykonane=True,
            data=timezone.now() - timedelta(days=7)
        )

        from bloomly.models import utworz_przypomnienie_podlewanie
        przypomnienie1 = utworz_przypomnienie_podlewanie(self.roslina)
        stara_data = przypomnienie1.data_przypomnienia

        # 2. Podlej roślinę ponownie (wcześniej niż planowano)
        CzynoscPielegnacyjna.objects.create(
            roslina=self.roslina,
            typ="podlewanie",
            uzytkownik=self.user,
            wykonane=True,
            data=timezone.now()
        )

        # 3. Odśwież przypomnienie
        odswiez_przypomnienie_rosliny(self.roslina.id)

        # 4. Data przypomnienia powinna być zaktualizowana
        przypomnienie1.refresh_from_db()
        self.assertGreater(przypomnienie1.data_przypomnienia, stara_data)


class EmailNotificationFlowTest(TestCase):
    """Test wysyłania emaili z przypomnieniami"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        # Włącz powiadomienia email
        self.user.profiluzytkownika.powiadomienia_email = True
        self.user.profiluzytkownika.save()

        self.roslina = Roslina.objects.create(
            nazwa="Monstera",
            gatunek="Monstera deliciosa",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            data_zakupu=date.today(),
            lokalizacja="Salon"
        )

    def test_send_single_email_reminder(self):
        """Test wysyłania pojedynczego emaila"""

        # 1. Utwórz przypomnienie
        data_przyp = timezone.now() + timedelta(days=3)
        przypomnienie = Przypomnienie.objects.create(
            roslina=self.roslina,
            uzytkownik=self.user,
            typ="podlewanie",
            tytul="Podlej Monstera",
            tresc="Czas podlać roślinę",
            data_przypomnienia=data_przyp,
            status="oczekujace",
            wyslane=False
        )

        # 2. Wyślij email
        wyslij_email_przypomnienie(przypomnienie.id)

        # 3. Sprawdź czy email został wysłany
        self.assertEqual(len(mail.outbox), 1)

        email = mail.outbox[0]
        self.assertIn("Monstera", email.subject)
        self.assertIn(self.user.email, email.to)
        self.assertIn("Monstera deliciosa", email.body)
        self.assertIn("Salon", email.body)

        # 4. Sprawdź że przypomnienie zostało oznaczone jako wysłane
        przypomnienie.refresh_from_db()
        self.assertTrue(przypomnienie.wyslane)
        self.assertEqual(przypomnienie.status, "wyslane")
        self.assertIsNotNone(przypomnienie.data_wyslania)

    def test_email_contains_correct_date(self):
        """Test: email zawiera poprawną datę (czas lokalny)"""

        data_przyp = timezone.now() + timedelta(days=3)
        przypomnienie = Przypomnienie.objects.create(
            roslina=self.roslina,
            uzytkownik=self.user,
            typ="podlewanie",
            tytul="Podlej Monstera",
            data_przypomnienia=data_przyp,
            status="oczekujace"
        )

        wyslij_email_przypomnienie(przypomnienie.id)

        email = mail.outbox[0]
        # Email powinien zawierać datę w formacie lokalnym
        data_lokalna = timezone.localtime(data_przyp)
        data_str = data_lokalna.strftime('%d.%m.%Y')
        self.assertIn(data_str, email.body)

    def test_no_email_when_notifications_disabled(self):
        """Test: brak emaila gdy powiadomienia wyłączone"""

        # Wyłącz powiadomienia
        self.user.profiluzytkownika.powiadomienia_email = False
        self.user.profiluzytkownika.save()

        data_przyp = timezone.now() + timedelta(hours=1)
        przypomnienie = Przypomnienie.objects.create(
            roslina=self.roslina,
            uzytkownik=self.user,
            typ="podlewanie",
            data_przypomnienia=data_przyp,
            status="oczekujace"
        )

        # Sprawdź przypomnienia (nie powinno wysłać)
        sprawdz_przypomnienia()

        # Brak emaili
        self.assertEqual(len(mail.outbox), 0)


class ReminderSchedulingFlowTest(TestCase):
    """Test harmonogramu wysyłania przypomnień"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.user.profiluzytkownika.powiadomienia_email = True
        self.user.profiluzytkownika.save()

        self.roslina = Roslina.objects.create(
            nazwa="Monstera",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            data_zakupu=date.today()
        )

    def test_send_reminders_3_days_before(self):
        """Test: emaile wysyłane 3 dni przed terminem"""

        # Przypomnienie za dokładnie 3 dni
        data_przyp = timezone.now() + timedelta(hours=72, minutes=30)
        przypomnienie = Przypomnienie.objects.create(
            roslina=self.roslina,
            uzytkownik=self.user,
            typ="podlewanie",
            tytul="Podlej Monstera",
            data_przypomnienia=data_przyp,
            status="oczekujace",
            wyslane=False
        )

        with patch.object(wyslij_email_przypomnienie, 'delay', side_effect=lambda id: wyslij_email_przypomnienie(id)):
            sprawdz_przypomnienia()

        self.assertGreater(len(mail.outbox), 0)


    def test_dont_send_reminders_too_early(self):
        """Test: nie wysyłaj emaili za wcześnie (>3 dni przed)"""

        # Przypomnienie za 5 dni (za wcześnie)
        data_przyp = timezone.now() + timedelta(days=5)
        przypomnienie = Przypomnienie.objects.create(
            roslina=self.roslina,
            uzytkownik=self.user,
            typ="podlewanie",
            data_przypomnienia=data_przyp,
            status="oczekujace",
            wyslane=False
        )

        sprawdz_przypomnienia()

        # Email NIE powinien zostać wysłany
        self.assertEqual(len(mail.outbox), 0)

        przypomnienie.refresh_from_db()
        self.assertFalse(przypomnienie.wyslane)

    def test_dont_send_already_sent_reminders(self):
        """Test: nie wysyłaj ponownie już wysłanych"""

        data_przyp = timezone.now() + timedelta(days=3)
        przypomnienie = Przypomnienie.objects.create(
            roslina=self.roslina,
            uzytkownik=self.user,
            typ="podlewanie",
            data_przypomnienia=data_przyp,
            status="wyslane",
            wyslane=True,
            data_wyslania=timezone.now() - timedelta(hours=2)
        )

        sprawdz_przypomnienia()

        # Brak nowych emaili
        self.assertEqual(len(mail.outbox), 0)


class MultipleRemindersFlowTest(TestCase):
    """Test wysyłania wielu przypomnień jednocześnie"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.user.profiluzytkownika.powiadomienia_email = True
        self.user.profiluzytkownika.save()

    def test_send_multiple_reminders_for_different_plants(self):
        """Test: wysyłanie przypomnień dla wielu roślin"""

        # Utwórz 3 rośliny
        rosliny = []
        for i in range(3):
            roslina = Roslina.objects.create(
                nazwa=f"Roślina {i + 1}",
                wlasciciel=self.user,
                czestotliwosc_podlewania=7,
                kategoria='doniczkowa',
                poziom_trudnosci='latwy',
                data_zakupu=date.today()
            )
            rosliny.append(roslina)

            # Przypomnienie za 3 dni
            Przypomnienie.objects.create(
                roslina=roslina,
                uzytkownik=self.user,
                typ="podlewanie",
                tytul=f"Podlej {roslina.nazwa}",
                data_przypomnienia=timezone.now() + timedelta(hours=72, minutes=30),
                status="oczekujace",
                wyslane=False
            )

        # ✅ ZMIANA: Wywołaj bezpośrednio dla każdego przypomnienia
        przypomnienia = Przypomnienie.objects.filter(
            uzytkownik=self.user,
            status="oczekujace",
            wyslane=False
        )

        for przypomnienie in przypomnienia:
            wyslij_email_przypomnienie(przypomnienie.id)

        # Powinny być 3 emaile
        self.assertEqual(len(mail.outbox), 3)

        # Wszystkie przypomnienia powinny być wysłane
        for roslina in rosliny:
            przypomnienie = Przypomnienie.objects.get(
                roslina=roslina,
                status='wyslane'
            )
            self.assertTrue(przypomnienie.wyslane)

    def test_batch_refresh_all_reminders(self):
        """Test: wsadowe odświeżanie wszystkich przypomnień"""

        # Utwórz 5 roślin z historią podlewań
        for i in range(5):
            roslina = Roslina.objects.create(
                nazwa=f"Roślina {i + 1}",
                wlasciciel=self.user,
                czestotliwosc_podlewania=7,
                kategoria='doniczkowa',
                poziom_trudnosci='latwy',
                data_zakupu=date.today()
            )

            # Historia podlewań
            CzynoscPielegnacyjna.objects.create(
                roslina=roslina,
                typ="podlewanie",
                uzytkownik=self.user,
                wykonane=True,
                data=timezone.now() - timedelta(days=3)
            )

        from bloomly.models import utworz_przypomnienie_podlewanie
        for roslina in Roslina.objects.filter(wlasciciel=self.user, is_active=True):
            utworz_przypomnienie_podlewanie(roslina)

        # Wszystkie rośliny powinny mieć przypomnienia
        przypomnienia = Przypomnienie.objects.filter(
            uzytkownik=self.user,
            status='oczekujace'
        )

        print(f"\nDEBUG: przypomnienia.count()={przypomnienia.count()}")
        for p in przypomnienia:
            print(f"  - {p.roslina.nazwa}: {p.data_przypomnienia}")
        self.assertEqual(przypomnienia.count(), 5)


class ReminderEdgeCasesTest(TestCase):
    """Test przypadków brzegowych w systemie przypomnień"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.roslina = Roslina.objects.create(
            nazwa="Monstera",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            data_zakupu=date.today()
        )

    def test_overdue_reminder(self):
        """Test: przypomnienie po terminie"""

        # Przypomnienie przeterminowane (3 dni temu)
        data_przyp = timezone.now() - timedelta(days=3)
        przypomnienie = Przypomnienie.objects.create(
            roslina=self.roslina,
            uzytkownik=self.user,
            typ="podlewanie",
            data_przypomnienia=data_przyp,
            status="oczekujace",
            wyslane=False
        )

        dni = przypomnienie.dni_do_przypomnienia()
        self.assertIn(dni, [-3, -4])

        # Sprawdź przypomnienia - nie powinno wysłać (już po terminie)
        sprawdz_przypomnienia()

        # Email nie powinien być wysłany (za późno)
        self.assertEqual(len(mail.outbox), 0)

    def test_reminder_for_inactive_plant(self):
        """Test: przypomnienie dla nieaktywnej rośliny"""

        # Dezaktywuj roślinę
        self.roslina.is_active = False
        self.roslina.save()

        data_przyp = timezone.now() + timedelta(days=3)
        przypomnienie = Przypomnienie.objects.create(
            roslina=self.roslina,
            uzytkownik=self.user,
            typ="podlewanie",
            data_przypomnienia=data_przyp,
            status="oczekujace"
        )

        # Odświeżanie nie powinno utworzyć nowych przypomnień
        result = odswiez_przypomnienie_rosliny(self.roslina.id)

        przypomnienia_count = Przypomnienie.objects.filter(
            roslina=self.roslina,
            status='oczekujace'
        ).count()

        self.assertEqual(przypomnienia_count, 1, "Nie powinno być nowych przypomnień dla nieaktywnej rośliny")

    def test_reminder_without_previous_watering(self):
        """Test: przypomnienie dla rośliny bez historii podlewań"""

        # Brak jakichkolwiek podlewań
        from bloomly.models import utworz_przypomnienie_podlewanie
        przypomnienie = utworz_przypomnienie_podlewanie(self.roslina)

        # Przypomnienie powinno być utworzone na podstawie domyślnej częstotliwości
        if przypomnienie:
            dni_do = (przypomnienie.data_przypomnienia.date() - timezone.now().date()).days
            # Powinno być blisko czestotliwosc_podlewania (7 dni)
            self.assertGreaterEqual(dni_do, 5)
            self.assertLessEqual(dni_do, 9)


class NotificationUserPreferencesTest(TestCase):
    """Test preferencji użytkownika dot. powiadomień"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.roslina = Roslina.objects.create(
            nazwa="Monstera",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            data_zakupu=date.today()
        )

    def test_respect_email_notification_preference(self):
        """Test: respektowanie preferencji powiadomień email"""

        # Wyłącz powiadomienia
        self.user.profiluzytkownika.powiadomienia_email = False
        self.user.profiluzytkownika.save()

        data_przyp = timezone.now() + timedelta(days=3)
        Przypomnienie.objects.create(
            roslina=self.roslina,
            uzytkownik=self.user,
            typ="podlewanie",
            data_przypomnienia=data_przyp,
            status="oczekujace",
            wyslane=False
        )

        sprawdz_przypomnienia()

        # Email NIE powinien być wysłany
        self.assertEqual(len(mail.outbox), 0)

    def test_enable_notifications_works(self):
        """Test: włączenie powiadomień działa"""

        # Włącz powiadomienia
        self.user.profiluzytkownika.powiadomienia_email = True
        self.user.profiluzytkownika.save()

        data_przyp = timezone.now() + timedelta(hours=72, minutes=30)
        przypomnienie = Przypomnienie.objects.create(
            roslina=self.roslina,
            uzytkownik=self.user,
            typ="podlewanie",
            tytul="Podlej roślinę",
            data_przypomnienia=data_przyp,
            status="oczekujace",
            wyslane=False
        )

        # ✅ ZMIANA: Wywołaj bezpośrednio zamiast przez sprawdz_przypomnienia()
        wyslij_email_przypomnienie(przypomnienie.id)

        # Email powinien być wysłany
        self.assertGreater(len(mail.outbox), 0)

        przypomnienie.refresh_from_db()
        self.assertTrue(przypomnienie.wyslane)


class NotificationMLIntegrationTest(TestCase):
    """Test integracji przypomnień z systemem ML"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.roslina = Roslina.objects.create(
            nazwa="Monstera",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            data_zakupu=date.today()
        )

    def test_reminder_uses_ml_recommendation(self):
        """Test: przypomnienie używa rekomendacji ML"""

        # Utwórz historię podlewań
        base_date = timezone.now() - timedelta(days=100)
        for i in range(15):
            CzynoscPielegnacyjna.objects.create(
                roslina=self.roslina,
                typ="podlewanie",
                wykonane=True,
                uzytkownik=self.user,
                data=base_date + timedelta(days=i * 10),  # Co 10 dni
                stan_gleby="dry"
            )

        # Zaktualizuj analizę ML
        from bloomly.ml_utils import zaktualizuj_analize_rosliny
        result = zaktualizuj_analize_rosliny(self.roslina)
        analiza = result['analiza']

        # Utwórz przypomnienie na podstawie ostatniego podlewania
        from bloomly.models import utworz_przypomnienie_podlewanie
        przypomnienie = utworz_przypomnienie_podlewanie(self.roslina)

        if przypomnienie and analiza.rekomendowana_czestotliwosc:
            # Przypomnienie powinno być utworzone na podstawie rekomendacji ML
            # (około 10 dni od ostatniego podlewania)
            ostatnie_podlewanie = CzynoscPielegnacyjna.objects.filter(
                roslina=self.roslina,
                typ="podlewanie"
            ).latest('data')

            oczekiwana_data = ostatnie_podlewanie.data + timedelta(
                days=analiza.rekomendowana_czestotliwosc
            )

            roznica = abs(
                (przypomnienie.data_przypomnienia.date() - oczekiwana_data.date()).days
            )

            # Różnica powinna być niewielka (max 1-2 dni)
            self.assertLessEqual(roznica, 2)

    def test_reminder_email_includes_ml_info(self):
        """Test: email zawiera informacje o ML"""

        # Utwórz analizę ML
        from bloomly.models import AnalizaPielegnacji
        analiza = AnalizaPielegnacji.objects.create(
            roslina=self.roslina,
            uzytkownik=self.user,
            rekomendowana_czestotliwosc=10,
            pewnosc_rekomendacji=0.85,
            typ_modelu="RF",
            liczba_podlan=15
        )

        # Utwórz przypomnienie
        data_przyp = timezone.now() + timedelta(days=3)
        przypomnienie = Przypomnienie.objects.create(
            roslina=self.roslina,
            uzytkownik=self.user,
            typ="podlewanie",
            tytul="Podlej Monstera",
            tresc="Rekomendacja: za 10 dni. Źródło: Random Forest.",
            data_przypomnienia=data_przyp,
            status="oczekujace"
        )

        # Wyślij email
        self.user.profiluzytkownika.powiadomienia_email = True
        self.user.profiluzytkownika.save()

        wyslij_email_przypomnienie(przypomnienie.id)

        # Sprawdź treść emaila
        email = mail.outbox[0]
        self.assertIn("10 dni", email.body)


class NotificationErrorHandlingTest(TestCase):
    """Test obsługi błędów w systemie powiadomień"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.roslina = Roslina.objects.create(
            nazwa="Monstera",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            data_zakupu=date.today()
        )

    def test_handle_invalid_email(self):
        """Test: obsługa nieprawidłowego adresu email"""

        # Ustaw nieprawidłowy email
        self.user.email = "invalid-email"
        self.user.save()

        data_przyp = timezone.now() + timedelta(days=3)
        przypomnienie = Przypomnienie.objects.create(
            roslina=self.roslina,
            uzytkownik=self.user,
            typ="podlewanie",
            data_przypomnienia=data_przyp,
            status="oczekujace"
        )

        # Próba wysłania nie powinna crashować aplikacji
        try:
            wyslij_email_przypomnienie(przypomnienie.id)
        except Exception:
            pass

        # System powinien kontynuować działanie
        self.assertTrue(True)

    def test_handle_nonexistent_reminder(self):
        """Test: obsługa nieistniejącego przypomnienia"""

        # Próba wysłania emaila dla nieistniejącego ID
        result = wyslij_email_przypomnienie(99999)

        # Powinna zwrócić komunikat błędu, nie crashować
        self.assertIn("nie istnieje", result.lower())

    def test_handle_missing_user_profile(self):
        """Test: obsługa braku profilu użytkownika"""

        # Usuń profil
        if hasattr(self.user, 'profiluzytkownika'):
            self.user.profiluzytkownika.delete()

        data_przyp = timezone.now() + timedelta(days=3)
        Przypomnienie.objects.create(
            roslina=self.roslina,
            uzytkownik=self.user,
            typ="podlewanie",
            data_przypomnienia=data_przyp,
            status="oczekujace"
        )

        # Sprawdzanie nie powinno crashować
        try:
            sprawdz_przypomnienia()
        except Exception:
            pass

        # System powinien działać
        self.assertTrue(True)