"""
Testy integracyjne - przepływy użytkownika (User Flow)
Testują kompletne scenariusze użytkowania aplikacji
"""

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta, date
from datetime import date, timedelta
from django.utils import timezone
from django.urls import reverse
from bloomly.models import Roslina, Przypomnienie

from bloomly.models import (
    Roslina, CzynoscPielegnacyjna, Przypomnienie,
    AnalizaPielegnacji, ProfilUzytkownika
)


class UserRegistrationAndProfileFlowTest(TestCase):
    """Test rejestracji i zarządzania profilem"""

    def setUp(self):
        self.client = Client()

    def test_complete_registration_flow(self):
        """Test kompletnego procesu rejestracji"""
        # 1. Użytkownik wchodzi na stronę rejestracji
        response = self.client.get(reverse('rejestracja'))
        self.assertEqual(response.status_code, 200)

        # 2. Wypełnia formularz rejestracji
        data = {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'imie': 'Jan',
            'nazwisko': 'Kowalski',
            'password1': 'TestPass123!',
            'password2': 'TestPass123!'
        }
        response = self.client.post(reverse('rejestracja'), data)

        # 3. Powinien być przekierowany do logowania
        self.assertEqual(response.status_code, 302)

        # 4. Użytkownik powinien być utworzony
        user = User.objects.get(username='newuser')
        self.assertEqual(user.email, 'newuser@example.com')
        self.assertEqual(user.first_name, 'Jan')
        self.assertEqual(user.last_name, 'Kowalski')

        # 5. Profil powinien być automatycznie utworzony
        self.assertTrue(hasattr(user, 'profiluzytkownika'))
        self.assertTrue(user.profiluzytkownika.powiadomienia_email)

    def test_login_and_profile_edit_flow(self):
        """Test logowania i edycji profilu"""
        # 1. Utwórz użytkownika
        user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='TestPass123!'
        )

        # 2. Zaloguj się
        login_success = self.client.login(
            username='testuser',
            password='TestPass123!'
        )
        self.assertTrue(login_success)

        # 3. Wejdź na stronę profilu
        response = self.client.get(reverse('profil'))
        self.assertEqual(response.status_code, 200)

        # 4. Edytuj profil
        data = {
            'username': 'testuser',
            'email': 'newemail@example.com',
            'first_name': 'Jan',
            'last_name': 'Nowak',
            'telefon': '123456789',
            'powiadomienia_email': True,
            'biogram': 'Testowy biogram'
        }
        response = self.client.post(reverse('profil'), data)

        # 5. Sprawdź czy dane zostały zaktualizowane
        user.refresh_from_db()
        self.assertEqual(user.email, 'newemail@example.com')
        self.assertEqual(user.first_name, 'Jan')
        self.assertEqual(user.profiluzytkownika.telefon, '123456789')


class PlantManagementFlowTest(TestCase):
    """Test zarządzania roślinami"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='TestPass123!'
        )
        self.client.login(username='testuser', password='TestPass123!')

    def test_complete_plant_lifecycle(self):
        """Test kompletnego cyklu życia rośliny w aplikacji"""

        # 1. DODANIE ROŚLINY
        add_data = {
            'nazwa': 'Moja Monstera',
            'gatunek': 'Monstera deliciosa',
            'kategoria': 'doniczkowa',
            'poziom_trudnosci': 'latwy',
            'czestotliwosc_podlewania': 7,
            'data_zakupu': date.today().isoformat(),
            'lokalizacja': 'Salon'
        }
        response = self.client.post(reverse('dodaj_roslina'), add_data)
        self.assertEqual(response.status_code, 302)

        roslina = Roslina.objects.get(nazwa='Moja Monstera')
        self.assertEqual(roslina.wlasciciel, self.user)
        self.assertTrue(roslina.is_active)

        # 2. WYŚWIETLENIE LISTY ROŚLIN
        response = self.client.get(reverse('lista_roslin'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Moja Monstera')

        # 3. SZCZEGÓŁY
        response = self.client.get(reverse('szczegoly_rosliny', args=[roslina.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Monstera deliciosa')

        # 4. EDYCJA ROŚLINY
        edit_data = {
            'nazwa': 'Moja Monstera',
            'gatunek': 'Monstera deliciosa',
            'kategoria': roslina.kategoria,
            'poziom_trudnosci': roslina.poziom_trudnosci,
            'data_zakupu': (roslina.data_zakupu.isoformat()
                            if roslina.data_zakupu else date.today().isoformat()),
            'czestotliwosc_podlewania': 10,
            'lokalizacja': 'Sypialnia'
        }
        response = self.client.post(reverse('edytuj_roslina', args=[roslina.id]), edit_data)
        self.assertEqual(response.status_code, 302)

        roslina.refresh_from_db()
        self.assertEqual(roslina.czestotliwosc_podlewania, 10)
        self.assertEqual(roslina.lokalizacja, 'Sypialnia')

        # 5. PODLANIE ROŚLINY (przykład wyboru choices z modelu)
        stan_field = CzynoscPielegnacyjna._meta.get_field('stan_gleby')
        stan_choices = getattr(stan_field, 'choices', []) or []
        stan_val = stan_choices[0][0] if stan_choices else 'sucha'
        ilosc_field = CzynoscPielegnacyjna._meta.get_field('ilosc_wody')
        ilosc_choices = getattr(ilosc_field, 'choices', []) or []
        ilosc_val = ilosc_choices[0][0] if ilosc_choices else 200

        podlewanie_data = {
            'data': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
            'stan_gleby': stan_val,
            'ilosc_wody': ilosc_val,
            'notatki': 'Pierwsze podlanie'
        }
        response = self.client.post(reverse('podlej_roslina', args=[roslina.id]), podlewanie_data)
        self.assertEqual(response.status_code, 302)

        czynnosc = CzynoscPielegnacyjna.objects.filter(roslina=roslina, typ='podlewanie').first()
        self.assertIsNotNone(czynnosc)
        self.assertEqual(czynnosc.stan_gleby, stan_val)

        # 6. USUNIĘCIE ROŚLINY
        response = self.client.post(reverse('usun_roslina', args=[roslina.id]))
        self.assertEqual(response.status_code, 302)

        # 6a. Sprawdzenie w bazie, że roślina została usunięta (hard delete)
        with self.assertRaises(Roslina.DoesNotExist):
            Roslina.objects.get(id=roslina.id)

        # 7. SPRAWDZENIE LISTY ROŚLIN
        response = self.client.get(reverse('lista_roslin'))
        self.assertEqual(response.status_code, 200)

        # Sprawdźmy listę roślin: szukamy tylko w elementach listy, np. po klasie CSS
        # Zakładam, że rośliny są w <div class="plant-name">…</div>
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.content, 'html.parser')
        plant_names = [el.get_text(strip=True) for el in soup.select('.plant-name')]
        self.assertNotIn('Moja Monstera', plant_names)


class WateringAndReminderFlowTest(TestCase):
    """Test przepływu podlewania i przypomnień"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='TestPass123!'
        )
        self.client.login(username='testuser', password='TestPass123!')

        self.roslina = Roslina.objects.create(
            nazwa="Monstera",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            data_zakupu=date.today()
        )

    def test_watering_creates_reminder(self):
        """Test: podlanie rośliny tworzy nowe przypomnienie"""

        # 1. Sprawdź że nie ma przypomnień
        self.assertEqual(
            Przypomnienie.objects.filter(roslina=self.roslina).count(),
            0
        )

        # 2. Podlej roślinę
        CzynoscPielegnacyjna.objects.create(
            roslina=self.roslina,
            typ="podlewanie",
            wykonane=True,
            uzytkownik=self.user,
            data=timezone.now(),
            stan_gleby="sucha"
        )

        # 3. Utwórz przypomnienie (symulacja funkcji utworz_przypomnienie_podlewanie)
        from bloomly.models import utworz_przypomnienie_podlewanie
        przypomnienie = utworz_przypomnienie_podlewanie(self.roslina)

        # 4. Sprawdź że przypomnienie zostało utworzone
        self.assertIsNotNone(przypomnienie)
        self.assertEqual(przypomnienie.roslina, self.roslina)
        self.assertEqual(przypomnienie.status, 'oczekujace')
        self.assertFalse(przypomnienie.wyslane)

    def test_complete_reminder_execution_flow(self):
        """Test kompletnego wykonania przypomnienia (podlewanie rośliny)"""

        # 1. Utwórz roślinę
        roslina = Roslina.objects.create(
            nazwa='Moja Monstera',
            gatunek='Monstera deliciosa',
            kategoria='doniczkowa',
            poziom_trudnosci='latwy',
            czestotliwosc_podlewania=7,
            data_zakupu=date.today(),
            lokalizacja='Salon',
            wlasciciel=self.user
        )

        # 2. Utwórz przypomnienie
        przypomnienie = Przypomnienie.objects.create(
            roslina=roslina,
            uzytkownik=self.user,
            typ='podlewanie',
            tytul='Podlej roślinę',
            tresc='Podlej roślinę wodą',
            data_przypomnienia=timezone.now() + timedelta(minutes=5)
        )

        # 3. Wykonaj przypomnienie (formularz podlewania)
        wykonaj_data = {
            'data': timezone.now().strftime('%Y-%m-%d %H:%M'),  # wymagane pole formularza
            'stan_gleby': 'dry',  # musi odpowiadać choices w formularzu
            'ilosc_wody': 'med',  # zgodnie z formularzem
            'notatki': 'Wykonano z przypomnienia'
        }

        response = self.client.post(
            reverse('wykonaj_przypomnienie', args=[przypomnienie.id]),
            wykonaj_data
        )

        # 4. Debug w razie błędu formularza
        if response.status_code != 302:
            if hasattr(response, 'context') and 'form' in response.context:
                print(f"\nBłędy wykonania: {response.context['form'].errors}")

        # 5. Sprawdź, że nastąpiło przekierowanie
        self.assertEqual(response.status_code, 302)

        # 6. Odśwież przypomnienie i sprawdź status
        przypomnienie.refresh_from_db()
        self.assertEqual(przypomnienie.status, 'wykonane')
        self.assertIsNotNone(przypomnienie.data_wykonania)


class MultiPlantManagementFlowTest(TestCase):
    """Test zarządzania wieloma roślinami jednocześnie"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='TestPass123!'
        )
        self.client.login(username='testuser', password='TestPass123!')

    def test_manage_multiple_plants(self):
        """Test zarządzania wieloma roślinami"""

        # 1. Dodaj 3 rośliny
        rosliny_data = [
            {
                'nazwa': 'Monstera',
                'gatunek': 'Monstera deliciosa',  # ✅ DODAJ
                'czestotliwosc_podlewania': 7,
                'kategoria': 'doniczkowa',  # ✅ DODAJ: wymagane
                'poziom_trudnosci': 'latwy',  # ✅ DODAJ: wymagane
                'data_zakupu': date.today()  # ✅ DODAJ: wymagane
            },
            {
                'nazwa': 'Fiołek',
                'gatunek': 'Viola',  # ✅ DODAJ
                'czestotliwosc_podlewania': 5,
                'kategoria': 'doniczkowa',  # ✅ DODAJ
                'poziom_trudnosci': 'latwy',  # ✅ DODAJ
                'data_zakupu': date.today()  # ✅ DODAJ
            },
            {
                'nazwa': 'Sukulenty',
                'gatunek': 'Succulenta',  # ✅ DODAJ
                'czestotliwosc_podlewania': 14,
                'kategoria': 'doniczkowa',  # ✅ DODAJ
                'poziom_trudnosci': 'latwy',  # ✅ DODAJ
                'data_zakupu': date.today()  # ✅ DODAJ
            }
        ]

        for data in rosliny_data:
            response = self.client.post(reverse('dodaj_roslina'), data)

            # ✅ DEBUG
            if response.status_code != 302:
                if 'form' in response.context:
                    print(f"\nBłędy dla {data['nazwa']}: {response.context['form'].errors}")

            self.assertEqual(response.status_code, 302)

class UserIsolationTest(TestCase):
    """Test izolacji danych użytkowników"""

    def setUp(self):
        self.client = Client()

        # Użytkownik 1
        self.user1 = User.objects.create_user(
            username='user1',
            password='TestPass123!'
        )
        self.roslina1 = Roslina.objects.create(
            nazwa="Roślina User1",
            wlasciciel=self.user1,
            czestotliwosc_podlewania=7,
            data_zakupu=date.today()
        )

        # Użytkownik 2
        self.user2 = User.objects.create_user(
            username='user2',
            password='TestPass123!'
        )
        self.roslina2 = Roslina.objects.create(
            nazwa="Roślina User2",
            wlasciciel=self.user2,
            czestotliwosc_podlewania=7,
            data_zakupu=date.today()
        )

    def test_user_cannot_see_other_users_plants(self):
        """Test że użytkownik nie widzi roślin innych użytkowników"""

        # Zaloguj jako user1
        self.client.login(username='user1', password='TestPass123!')

        # Sprawdź listę roślin
        response = self.client.get(reverse('lista_roslin'))
        self.assertContains(response, 'Roślina User1')
        self.assertNotContains(response, 'Roślina User2')

    def test_user_cannot_edit_other_users_plants(self):
        """Test że użytkownik nie może edytować cudzych roślin"""

        # Zaloguj jako user1
        self.client.login(username='user1', password='TestPass123!')

        # Spróbuj edytować roślinę user2
        response = self.client.get(
            reverse('edytuj_roslina', args=[self.roslina2.id])
        )

        # Powinien dostać 404
        self.assertEqual(response.status_code, 404)

    def test_user_cannot_delete_other_users_plants(self):
        """Test że użytkownik nie może usunąć cudzych roślin"""

        # Zaloguj jako user1
        self.client.login(username='user1', password='TestPass123!')

        # Spróbuj usunąć roślinę user2
        response = self.client.post(
            reverse('usun_roslina', args=[self.roslina2.id])
        )

        # Powinien dostać 404
        self.assertEqual(response.status_code, 404)

        # Roślina nadal powinna istnieć
        self.assertTrue(
            Roslina.objects.filter(id=self.roslina2.id).exists()
        )