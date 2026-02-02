"""
Testy jednostkowe formularzy
"""

from django.test import TestCase
from django.contrib.auth.models import User
from bloomly.forms import (
    RoslinaForm, ProfilForm, PodlewanieForm,
    CzynoscForm, RejestracjaForm, PostForm
)
from bloomly.models import Roslina, ProfilUzytkownika


class RoslinaFormUnitTest(TestCase):
    """Testy jednostkowe formularza rośliny"""

    def test_valid_form_minimal_data(self):
        """Test poprawnego formularza z minimalnymi danymi"""
        data = {
            'nazwa': 'Monstera',
            'gatunek': 'Monstera deliciosa',
            'czestotliwosc_podlewania': 7,
            'kategoria': 'doniczkowa',
            'poziom_trudnosci': 'latwy',
            'data_zakupu': '2024-01-01',
        }
        form = RoslinaForm(data=data)

        if not form.is_valid():
            print(f"\n❌ BŁĘDY: {form.errors}")

        self.assertTrue(form.is_valid())

    def test_valid_form_all_fields(self):
        """Test poprawnego formularza ze wszystkimi polami"""
        data = {
            'nazwa': 'Monstera Deliciosa',
            'gatunek': 'Monstera deliciosa',  # ✅ TEKST
            'czestotliwosc_podlewania': 10,
            'kategoria': 'doniczkowa',
            'poziom_trudnosci': 'latwy',
            'data_zakupu': '2025-11-01',
            'lokalizacja': 'Salon',
            'notatki': 'Piękna roślina'
        }
        form = RoslinaForm(data=data)

        if not form.is_valid():
            print(f"\n❌ BŁĘDY: {form.errors}")

        self.assertTrue(form.is_valid())

    def test_nazwa_required(self):
        """Test czy nazwa jest wymagana"""
        data = {
            'czestotliwosc_podlewania': 7
        }
        form = RoslinaForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('nazwa', form.errors)

    def test_czestotliwosc_required(self):
        """Test czy częstotliwość jest wymagana"""
        data = {
            'nazwa': 'Monstera'
        }
        form = RoslinaForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('czestotliwosc_podlewania', form.errors)

    def test_czestotliwosc_must_be_positive(self):
        """Test czy częstotliwość musi być dodatnia"""
        data = {
            'nazwa': 'Monstera',
            'czestotliwosc_podlewania': -5
        }
        form = RoslinaForm(data=data)
        self.assertFalse(form.is_valid())

    def test_czestotliwosc_cannot_be_zero(self):
        """Test czy częstotliwość nie może być zerem"""
        data = {
            'nazwa': 'Monstera',
            'czestotliwosc_podlewania': 0
        }
        form = RoslinaForm(data=data)
        self.assertFalse(form.is_valid())


class ProfilFormUnitTest(TestCase):
    """Testy jednostkowe formularza profilu"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.profil = self.user.profiluzytkownika

    def test_valid_form(self):
        """Test poprawnego formularza"""
        data = {
            'telefon': '123456789',
            'powiadomienia_email': True,
            'biogram': 'Testowy biogram'
        }
        form = ProfilForm(data=data, instance=self.profil)
        self.assertTrue(form.is_valid())

    def test_telefon_optional(self):
        """Test czy telefon jest opcjonalny"""
        data = {
            'telefon': '',
            'powiadomienia_email': True
        }
        form = ProfilForm(data=data, instance=self.profil)
        self.assertTrue(form.is_valid())

    def test_powiadomienia_email_checkbox(self):
        """Test pola powiadomień email"""
        data = {
            'telefon': '123456789',
            'powiadomienia_email': False
        }
        form = ProfilForm(data=data, instance=self.profil)
        self.assertTrue(form.is_valid())
        self.assertFalse(form.cleaned_data['powiadomienia_email'])

    def test_data_urodzenia_format(self):
        """Test formatu daty urodzenia"""
        data = {
            'telefon': '123456789',
            'powiadomienia_email': True,
            'data_urodzenia': '1990-01-01'
        }
        form = ProfilForm(data=data, instance=self.profil)
        self.assertTrue(form.is_valid())

    def test_biogram_max_length(self):
        """Test maksymalnej długości biogramu"""
        data = {
            'telefon': '123456789',
            'powiadomienia_email': True,
            'biogram': 'A' * 700  # Powyżej 600 znaków
        }
        form = ProfilForm(data=data, instance=self.profil)
        self.assertFalse(form.is_valid())
        self.assertIn('biogram', form.errors)


class PodlewanieFormUnitTest(TestCase):
    """Testy jednostkowe formularza podlewania"""

    def setUp(self):
        from django.contrib.auth.models import User
        from bloomly.models import Roslina

        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.roslina = Roslina.objects.create(
            nazwa='Test Plant',
            gatunek='Test Species',
            czestotliwosc_podlewania=7,
            kategoria='doniczkowa',
            poziom_trudnosci='latwy',
            data_zakupu='2024-01-01',
            wlasciciel=self.user  # ✅ ZMIENIONE z 'user' na 'wlasciciel'
        )

    def test_valid_podlewanie_form(self):
        """Test poprawnego formularza podlewania"""
        from django.utils import timezone

        data = {
            'data': timezone.now().strftime('%Y-%m-%dT%H:%M'),  # ✅ Format dla datetime-local
            'stan_gleby': 'dry',
            'ilosc_wody': 'low',
            'notatki': 'Testowe podlewanie'
        }
        form = PodlewanieForm(data=data)

        if not form.is_valid():
            print(f"\n❌ BŁĘDY PODLEWANIE: {form.errors}")

        self.assertTrue(form.is_valid())

    def test_stan_gleby_optional(self):
        """Test czy stan gleby jest opcjonalny"""
        from django.utils import timezone

        data = {
            'data': timezone.now().strftime('%Y-%m-%dT%H:%M'),
            'ilosc_wody': 'med'
        }
        form = PodlewanieForm(data=data)

        if not form.is_valid():
            print(f"\n❌ BŁĘDY (optional): {form.errors}")

        self.assertTrue(form.is_valid())

    def test_data_default_value(self):
        """Test domyślnej wartości daty"""
        form = PodlewanieForm()
        self.assertIsNotNone(form.initial.get('data'))


class CzynoscFormUnitTest(TestCase):
    """Testy jednostkowe formularza czynności"""

    def test_valid_czynnosc_form(self):
        """Test poprawnego formularza czynności"""
        from django.utils import timezone
        data = {
            'typ': 'podlewanie',
            'data': timezone.now(),
            'notatki': 'Test'
        }
        form = CzynoscForm(data=data)
        self.assertTrue(form.is_valid())

    def test_typ_choices(self):
        """Test dostępnych typów czynności"""
        form = CzynoscForm()
        typ_field = form.fields['typ']
        self.assertIsNotNone(typ_field.choices)


class RejestracjaFormUnitTest(TestCase):
    """Testy jednostkowe formularza rejestracji"""

    def test_valid_registration(self):
        """Test poprawnej rejestracji"""
        data = {
            'username': 'newuser',
            'email': 'new@example.com',
            'imie': 'Jan',
            'nazwisko': 'Kowalski',
            'password1': 'TestPass123!',
            'password2': 'TestPass123!'
        }
        form = RejestracjaForm(data=data)
        self.assertTrue(form.is_valid())

    def test_passwords_must_match(self):
        """Test czy hasła muszą się zgadzać"""
        data = {
            'username': 'newuser',
            'email': 'new@example.com',
            'imie': 'Jan',
            'nazwisko': 'Kowalski',
            'password1': 'TestPass123!',
            'password2': 'DifferentPass123!'
        }
        form = RejestracjaForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('password2', form.errors)

    def test_username_required(self):
        """Test czy username jest wymagany"""
        data = {
            'email': 'new@example.com',
            'imie': 'Jan',
            'nazwisko': 'Kowalski',
            'password1': 'TestPass123!',
            'password2': 'TestPass123!'
        }
        form = RejestracjaForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('username', form.errors)

    def test_email_required(self):
        """Test czy email jest wymagany"""
        data = {
            'username': 'newuser',
            'imie': 'Jan',
            'nazwisko': 'Kowalski',
            'password1': 'TestPass123!',
            'password2': 'TestPass123!'
        }
        form = RejestracjaForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)

    def test_save_creates_user_with_names(self):
        """Test czy zapisanie formularza tworzy użytkownika z imieniem i nazwiskiem"""
        data = {
            'username': 'newuser',
            'email': 'new@example.com',
            'imie': 'Jan',
            'nazwisko': 'Kowalski',
            'password1': 'TestPass123!',
            'password2': 'TestPass123!'
        }
        form = RejestracjaForm(data=data)
        self.assertTrue(form.is_valid())

        user = form.save()
        self.assertEqual(user.first_name, 'Jan')
        self.assertEqual(user.last_name, 'Kowalski')
        self.assertEqual(user.email, 'new@example.com')


class PostFormUnitTest(TestCase):
    """Testy jednostkowe formularza posta"""

    def setUp(self):
        from bloomly.models import Kategoria
        self.kategoria = Kategoria.objects.create(
            nazwa="Testowa kategoria",
            slug="testowa",
            typ="forum",
            aktywna=True
        )

    def test_valid_post_form(self):
        """Test poprawnego formularza posta"""
        data = {
            'tytul': 'Testowy post',
            'kategoria': self.kategoria.id,
            'tresc': 'Treść testowego posta'
        }
        form = PostForm(data=data)
        # Form needs to be initialized to set up kategoria queryset
        form.fields['kategoria'].queryset = form.fields['kategoria'].queryset.model.objects.filter(
            typ="forum", aktywna=True
        )
        self.assertTrue(form.is_valid())

    def test_tytul_required(self):
        """Test czy tytuł jest wymagany"""
        data = {
            'kategoria': self.kategoria.id,
            'tresc': 'Treść'
        }
        form = PostForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('tytul', form.errors)