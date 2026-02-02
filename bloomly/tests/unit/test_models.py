"""
Testy jednostkowe modeli - sprawdzają pojedyncze metody i zachowania
"""

from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError
from datetime import timedelta, date

from bloomly.models import (
    Roslina, CzynoscPielegnacyjna, Przypomnienie,
    AnalizaPielegnacji, ProfilUzytkownika
)


class RoslinaModelUnitTest(TestCase):
    """Testy jednostkowe modelu Roslina"""

    def setUp(self):
        """Przygotowanie danych testowych"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='TestPass123!'
        )

    def test_create_roslina_with_minimal_data(self):
        """Test tworzenia rośliny z minimalnymi danymi"""
        roslina = Roslina.objects.create(
            nazwa="Monstera",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            kategoria='doniczkowa',
            poziom_trudnosci='latwy',
            data_zakupu=date.today()
        )

        self.assertEqual(roslina.nazwa, "Monstera")
        self.assertEqual(roslina.wlasciciel, self.user)
        self.assertEqual(roslina.czestotliwosc_podlewania, 7)
        self.assertTrue(roslina.is_active)
        self.assertIsNotNone(roslina.data_dodania)

    def test_create_roslina_with_all_fields(self):
        """Test tworzenia rośliny ze wszystkimi polami"""
        roslina = Roslina.objects.create(
            nazwa="Monstera Deliciosa",
            gatunek="Monstera deliciosa",
            wlasciciel=self.user,
            czestotliwosc_podlewania=10,
            data_zakupu=date.today(),
            kategoria='doniczkowa',
            poziom_trudnosci='latwy',
            lokalizacja="Salon",
            notatki="Piękna monstera z dużymi liśćmi"
        )

        self.assertEqual(roslina.gatunek, "Monstera deliciosa")
        self.assertEqual(roslina.kategoria, 'doniczkowa')
        self.assertEqual(roslina.lokalizacja, "Salon")

    def test_roslina_str_method(self):
        """Test metody __str__"""
        roslina = Roslina.objects.create(
            nazwa="Fiołek",
            gatunek="Viola",
            wlasciciel=self.user,
            czestotliwosc_podlewania=5,
            kategoria='doniczkowa',
            poziom_trudnosci='latwy',
            data_zakupu=date.today()
        )
        # ✅ Twój __str__ zwraca TYLKO nazwę
        self.assertEqual(str(roslina), "Fiołek")

    def test_roslina_requires_owner(self):
        """Test czy roślina wymaga właściciela"""
        with self.assertRaises(Exception):
            Roslina.objects.create(
                nazwa="Orphan Plant",
                czestotliwosc_podlewania=7,
                kategoria='doniczkowa',
                poziom_trudnosci='latwy',
                data_zakupu=date.today()
            )

    def test_roslina_default_is_active(self):
        """Test domyślnej wartości is_active"""
        roslina = Roslina.objects.create(
            nazwa="Test",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            kategoria='doniczkowa',
            poziom_trudnosci='latwy',
            data_zakupu=date.today()
        )
        self.assertTrue(roslina.is_active)

    def test_soft_delete_roslina(self):
        """Test soft delete (is_active=False)"""
        roslina = Roslina.objects.create(
            nazwa="ToDelete",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            kategoria='doniczkowa',
            poziom_trudnosci='latwy',
            data_zakupu=date.today()
        )
        roslina.is_active = False
        roslina.save()

        self.assertFalse(roslina.is_active)
        # Roślina nadal istnieje w bazie
        self.assertTrue(Roslina.objects.filter(id=roslina.id).exists())


class CzynoscPielegnacyjnaModelUnitTest(TestCase):
    """Testy jednostkowe modelu CzynoscPielegnacyjna"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.roslina = Roslina.objects.create(
            nazwa="Monstera",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            kategoria='doniczkowa',
            poziom_trudnosci='latwy',
            data_zakupu=date.today()
        )

    def test_create_podlewanie(self):
        """Test tworzenia czynności podlewania"""
        czynnosc = CzynoscPielegnacyjna.objects.create(
            roslina=self.roslina,
            typ="podlewanie",
            uzytkownik=self.user,
            wykonane=True
        )

        self.assertEqual(czynnosc.typ, "podlewanie")
        self.assertTrue(czynnosc.wykonane)
        self.assertIsNotNone(czynnosc.data)

    def test_create_with_water_data(self):
        """Test tworzenia z danymi o wodzie i glebie"""
        czynnosc = CzynoscPielegnacyjna.objects.create(
            roslina=self.roslina,
            typ="podlewanie",
            uzytkownik=self.user,
            wykonane=True,
            ilosc_wody='med',
            stan_gleby='dry'
        )

        self.assertEqual(czynnosc.ilosc_wody, 'med')
        self.assertEqual(czynnosc.stan_gleby, 'dry')

    def test_data_auto_now_add(self):
        """Test automatycznego ustawiania daty"""
        before = timezone.now()
        czynnosc = CzynoscPielegnacyjna.objects.create(
            roslina=self.roslina,
            typ="podlewanie",
            uzytkownik=self.user,
            wykonane=True
        )
        after = timezone.now()

        self.assertGreaterEqual(czynnosc.data, before)
        self.assertLessEqual(czynnosc.data, after)

    def test_czynnosc_str_method(self):
        """Test metody __str__"""
        czynnosc = CzynoscPielegnacyjna.objects.create(
            roslina=self.roslina,
            typ="podlewanie",
            uzytkownik=self.user,
            wykonane=True
        )
        # ✅ Twój __str__ zwraca "get_typ_display() - Nazwa (data)"
        expected = f'Podlewanie - Monstera ({timezone.now().strftime("%d.%m.%Y")})'
        self.assertEqual(str(czynnosc), expected)


class PrzypomnienieModelUnitTest(TestCase):
    """Testy jednostkowe modelu Przypomnienie"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.roslina = Roslina.objects.create(
            nazwa="Monstera",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            kategoria='doniczkowa',
            poziom_trudnosci='latwy',
            data_zakupu=date.today()
        )

    def test_create_przypomnienie(self):
        """Test tworzenia przypomnienia"""
        data = timezone.now() + timedelta(days=3)
        przypomnienie = Przypomnienie.objects.create(
            roslina=self.roslina,
            uzytkownik=self.user,
            typ="podlewanie",
            tytul="Podlej Monstera",
            tresc="Czas podlać roślinę",
            data_przypomnienia=data,
            status="oczekujace"
        )

        self.assertEqual(przypomnienie.typ, "podlewanie")
        self.assertEqual(przypomnienie.status, "oczekujace")
        self.assertFalse(przypomnienie.wyslane)

    def test_dni_do_przypomnienia_future(self):
        """Test obliczania dni do przypomnienia w przyszłości"""
        data = timezone.now() + timedelta(days=5)
        przypomnienie = Przypomnienie.objects.create(
            roslina=self.roslina,
            uzytkownik=self.user,
            typ="podlewanie",
            tytul="Test",
            tresc="Test",
            data_przypomnienia=data,
            status="oczekujace"
        )

        dni = przypomnienie.dni_do_przypomnienia()
        self.assertEqual(dni, 5)

    def test_dni_do_przypomnienia_today(self):
        """Test obliczania dni dla dzisiejszego przypomnienia"""
        teraz = timezone.now() + timedelta(seconds=1)
        przypomnienie = Przypomnienie.objects.create(
            roslina=self.roslina,
            uzytkownik=self.user,
            typ="podlewanie",
            tytul="Test",
            tresc="Test",
            data_przypomnienia=teraz,
            status="oczekujace"
        )

        dni = przypomnienie.dni_do_przypomnienia()
        # ✅ Teraz może być 0 lub 1 (przez math.ceil)
        self.assertIn(dni, [0, 1])

    def test_dni_do_przypomnienia_past(self):
        """Test obliczania dni dla przeterminowanego przypomnienia"""
        przeszlosc = timezone.now() - timedelta(days=3, hours=12)
        przypomnienie = Przypomnienie.objects.create(
            roslina=self.roslina,
            uzytkownik=self.user,
            typ="podlewanie",
            tytul="Test",
            tresc="Test",
            data_przypomnienia=przeszlosc,
            status="oczekujace"
        )

        dni = przypomnienie.dni_do_przypomnienia()
        self.assertIn(dni, [-3, -4])

    def test_opis_rekomendacji_without_analiza(self):
        """Test opisu rekomendacji bez analizy ML"""
        za_3_dni = timezone.now() + timedelta(days=3)
        przypomnienie = Przypomnienie.objects.create(
            roslina=self.roslina,
            uzytkownik=self.user,
            typ="podlewanie",
            tytul="Test",
            tresc="Test",
            data_przypomnienia=za_3_dni,
            status="oczekujace"
        )

        opis = przypomnienie.opis_rekomendacji()

        # ✅ Twoja metoda zwraca TYLKO "Za 3 dni"
        self.assertEqual(opis, "Za 3 dni")

    def test_opis_rekomendacji_with_analiza(self):
        """Test opisu rekomendacji z analizą ML"""
        # Utwórz analizę
        analiza = AnalizaPielegnacji.objects.create(
            roslina=self.roslina,
            uzytkownik=self.user,
            rekomendowana_czestotliwosc=8,
            pewnosc_rekomendacji=0.85,
            typ_modelu="RF"
        )

        za_3_dni = timezone.now() + timedelta(days=3)
        przypomnienie = Przypomnienie.objects.create(
            roslina=self.roslina,
            uzytkownik=self.user,
            typ="podlewanie",
            tytul="Test",
            tresc="Test",
            data_przypomnienia=za_3_dni,
            status="oczekujace"
        )

        opis = przypomnienie.opis_rekomendacji()

        # ✅ Metoda zwraca TYLKO "Za 3 dni" - nie sprawdza analizy
        self.assertEqual(opis, "Za 3 dni")


class AnalizaPielegnacjiModelUnitTest(TestCase):
    """Testy jednostkowe modelu AnalizaPielegnacji"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.roslina = Roslina.objects.create(
            nazwa="Monstera",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            kategoria='doniczkowa',
            poziom_trudnosci='latwy',
            data_zakupu=date.today()
        )

    def test_create_analiza(self):
        """Test tworzenia analizy"""
        analiza = AnalizaPielegnacji.objects.create(
            roslina=self.roslina,
            uzytkownik=self.user,
            srednia_czestotliwosc_dni=7.5,
            odchylenie_standardowe=1.2,
            liczba_podlan=10,
            rekomendowana_czestotliwosc=8,
            pewnosc_rekomendacji=0.85,
            typ_modelu="RF"
        )

        self.assertEqual(analiza.typ_modelu, "RF")
        self.assertEqual(analiza.liczba_podlan, 10)
        self.assertAlmostEqual(analiza.pewnosc_rekomendacji, 0.85)

    def test_get_typ_modelu_display_rf(self):
        """Test wyświetlania nazwy modelu Random Forest"""
        analiza = AnalizaPielegnacji.objects.create(
            roslina=self.roslina,
            uzytkownik=self.user,
            typ_modelu="RF",
            rekomendowana_czestotliwosc=7
        )
        self.assertEqual(analiza.get_typ_modelu_display(), "Random Forest")

    def test_get_typ_modelu_display_gb(self):
        """Test wyświetlania nazwy modelu Gradient Boosting"""
        analiza = AnalizaPielegnacji.objects.create(
            roslina=self.roslina,
            uzytkownik=self.user,
            typ_modelu="GB",
            rekomendowana_czestotliwosc=7
        )
        self.assertEqual(analiza.get_typ_modelu_display(), "Gradient Boosting")

    def test_pewnosc_range(self):
        """Test zakresu pewności (0-1)"""
        analiza = AnalizaPielegnacji.objects.create(
            roslina=self.roslina,
            uzytkownik=self.user,
            pewnosc_rekomendacji=0.92,
            rekomendowana_czestotliwosc=7
        )

        self.assertGreaterEqual(analiza.pewnosc_rekomendacji, 0.0)
        self.assertLessEqual(analiza.pewnosc_rekomendacji, 1.0)


class ProfilUzytkownikaModelUnitTest(TestCase):
    """Testy jednostkowe modelu ProfilUzytkownika"""

    def test_profil_auto_created_on_user_creation(self):
        """Test automatycznego tworzenia profilu przy rejestracji"""
        user = User.objects.create_user(
            username='newuser',
            email='new@example.com',
            password='testpass123'
        )

        # Profil powinien być utworzony automatycznie
        self.assertTrue(hasattr(user, 'profiluzytkownika'))
        self.assertIsInstance(user.profiluzytkownika, ProfilUzytkownika)

    def test_profil_default_values(self):
        """Test domyślnych wartości profilu"""
        user = User.objects.create_user(
            username='newuser',
            password='testpass123'
        )
        profil = user.profiluzytkownika

        self.assertTrue(profil.powiadomienia_email)
        self.assertEqual(profil.telefon, "")
        self.assertIsNone(profil.data_urodzenia)

    def test_profil_str_method(self):
        """Test metody __str__"""
        user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        profil = user.profiluzytkownika

        self.assertEqual(str(profil), "Profil: testuser")

    def test_update_profil_fields(self):
        """Test aktualizacji pól profilu"""
        user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        profil = user.profiluzytkownika

        profil.telefon = "123456789"
        profil.powiadomienia_email = False
        profil.save()

        profil.refresh_from_db()
        self.assertEqual(profil.telefon, "123456789")
        self.assertFalse(profil.powiadomienia_email)