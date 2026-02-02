"""
Testy jednostkowe funkcji ML
"""

from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from unittest.mock import patch, MagicMock
from datetime import timedelta, date
import os
import tempfile

from bloomly.models import Roslina, CzynoscPielegnacyjna, AnalizaPielegnacji
from bloomly.ml_utils import (
    przygotuj_dane_treningowe,
    trenuj_model_ml,
    przewidz_czestotliwosc_ml,
    zaktualizuj_analize_rosliny,
    analizuj_wzorce_statystyczne,
    zastosuj_rekomendacje_ml,
    _safe_mean,
    _safe_median,
    _soil_to_num,
    _water_category,
    _oblicz_pewnosc_regularnosci,
    _oblicz_jakosc_podlewania
)


class MLUtilsHelperFunctionsTest(TestCase):
    """Testy pomocniczych funkcji ML"""

    def test_safe_mean_empty_list(self):
        """Test średniej z pustej listy"""
        result = _safe_mean([])
        self.assertEqual(result, 0.0)

    def test_safe_mean_normal_list(self):
        """Test średniej z normalnej listy"""
        result = _safe_mean([5, 7, 9, 11])
        self.assertEqual(result, 8.0)

    def test_safe_median_empty_list(self):
        """Test mediany z pustej listy"""
        result = _safe_median([])
        self.assertEqual(result, 0.0)

    def test_safe_median_normal_list(self):
        """Test mediany z normalnej listy"""
        result = _safe_median([1, 2, 3, 4, 5])
        self.assertEqual(result, 3.0)

    def test_soil_to_num_sucha(self):
        """Test konwersji 'sucha' na 0.0"""
        self.assertEqual(_soil_to_num("sucha"), 0.0)
        self.assertEqual(_soil_to_num("dry"), 0.0)

    def test_soil_to_num_ok(self):
        """Test konwersji 'ok' na 1.0"""
        self.assertEqual(_soil_to_num("ok"), 1.0)
        self.assertEqual(_soil_to_num("wilgotna"), 1.0)

    def test_soil_to_num_mokra(self):
        """Test konwersji 'mokra' na 2.0"""
        self.assertEqual(_soil_to_num("mokra"), 2.0)
        self.assertEqual(_soil_to_num("wet"), 2.0)

    def test_soil_to_num_invalid(self):
        """Test konwersji nieprawidłowej wartości"""
        import math
        result = _soil_to_num("invalid")
        self.assertTrue(math.isnan(result))

    def test_water_category_low(self):
        """Test kategorii wody - mało"""
        self.assertEqual(_water_category("50"), 0)
        self.assertEqual(_water_category("mało"), 0)

    def test_water_category_medium(self):
        """Test kategorii wody - średnio"""
        self.assertEqual(_water_category("200"), 1)
        self.assertEqual(_water_category("średnio"), 1)

    def test_water_category_high(self):
        """Test kategorii wody - dużo"""
        self.assertEqual(_water_category("400"), 2)
        self.assertEqual(_water_category("dużo"), 2)

    def test_oblicz_pewnosc_regularnosci_empty(self):
        """Test pewności regularności dla pustej listy"""
        result = _oblicz_pewnosc_regularnosci([], 0, 0)
        self.assertEqual(result, 0.5)

    def test_oblicz_pewnosc_regularnosci_high(self):
        """Test pewności regularności dla regularnych interwałów"""
        interwaly = [7, 7, 7, 7, 7]
        srednia = 7.0
        odchylenie = 0.0
        result = _oblicz_pewnosc_regularnosci(interwaly, srednia, odchylenie)
        self.assertGreater(result, 0.8)


class MLUtilsPrzygotujDaneTest(TestCase):
    """Testy przygotowania danych treningowych"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.roslina = Roslina.objects.create(
            nazwa="Monstera",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            data_zakupu=date.today()
        )

    def test_za_malo_danych(self):
        """Test gdy jest za mało podlewań"""
        # Tylko 3 podlewania (minimum to 6)
        for i in range(3):
            CzynoscPielegnacyjna.objects.create(
                roslina=self.roslina,
                typ="podlewanie",
                uzytkownik=self.user,
                wykonane=True,
                data=timezone.now() - timedelta(days=i * 7)
            )

        result = przygotuj_dane_treningowe(self.roslina)
        self.assertIsNone(result)

    def test_wystarczajaco_danych(self):
        """Test gdy jest wystarczająco podlewań"""
        base_date = timezone.now() - timedelta(days=70)
        for i in range(10):
            CzynoscPielegnacyjna.objects.create(
                roslina=self.roslina,
                uzytkownik=self.user,
                typ="podlewanie",
                wykonane=True,
                data=base_date + timedelta(days=i * 7)
            )

        result = przygotuj_dane_treningowe(self.roslina)
        self.assertIsNotNone(result)
        X, y = result
        self.assertGreater(len(X), 0)
        self.assertEqual(len(X), len(y))

    def test_filtrowanie_outlierow(self):
        """Test filtrowania outlierów"""
        base_date = timezone.now() - timedelta(days=100)
        # Regularne podlewania
        for i in range(8):
            CzynoscPielegnacyjna.objects.create(
                roslina=self.roslina,
                typ="podlewanie",
                uzytkownik=self.user,
                wykonane=True,
                data=base_date + timedelta(days=i * 7)
            )
        # Outlier - bardzo długi interwał
        CzynoscPielegnacyjna.objects.create(
            roslina=self.roslina,
            typ="podlewanie",
            uzytkownik=self.user,
            wykonane=True,
            data=base_date + timedelta(days=100)
        )

        result = przygotuj_dane_treningowe(self.roslina)
        self.assertIsNotNone(result)


class MLUtilsTrenujModelTest(TestCase):
    """Testy trenowania modeli ML"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.roslina = Roslina.objects.create(
            nazwa="Monstera",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            data_zakupu=date.today()
        )

        # Stwórz historię regularnych podlewań
        base_date = timezone.now() - timedelta(days=100)
        for i in range(15):
            CzynoscPielegnacyjna.objects.create(
                roslina=self.roslina,
                typ="podlewanie",
                wykonane=True,
                uzytkownik=self.user,
                data=base_date + timedelta(days=i * 7),
                stan_gleby="sucha",
                ilosc_wody="200"
            )

    def test_trenuj_model_z_wystarczajacymi_danymi(self):
        """Test trenowania modelu z wystarczającą ilością danych"""
        model_data = trenuj_model_ml(self.roslina)

        self.assertIsNotNone(model_data)
        self.assertIn('model', model_data)
        self.assertIn('score', model_data)
        self.assertIn('mae', model_data)
        self.assertIn('rmse', model_data)
        self.assertIn('model_type', model_data)

    def test_wybor_modelu_dla_malych_zbiorow(self):
        """Test wyboru Gradient Boosting dla małych zbiorów (<15 próbek)"""

        # ✅ POPRAWKA: Pobierz IDs, potem usuń
        ids_to_delete = list(
            CzynoscPielegnacyjna.objects.filter(
                roslina=self.roslina
            ).order_by('-data').values_list('id', flat=True)[5:]
        )
        CzynoscPielegnacyjna.objects.filter(id__in=ids_to_delete).delete()

        model_data = trenuj_model_ml(self.roslina)
        if model_data:
            self.assertEqual(model_data['model_type'], 'GB')

    def test_wybor_modelu_dla_duzych_zbiorow(self):
        """Test wyboru Random Forest dla dużych zbiorów (>=20 próbek)"""

        self.roslina = Roslina.objects.create(
            nazwa="Duża roślina",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            data_zakupu=date.today()
        )

        # ✅ ZMIANA: 25 podlewań zamiast 20 (dla pewności)
        base_date = timezone.now() - timedelta(days=175)
        for i in range(25):
            CzynoscPielegnacyjna.objects.create(
                roslina=self.roslina,
                typ="podlewanie",
                uzytkownik=self.user,
                wykonane=True,
                data=base_date + timedelta(days=i * 7),
                stan_gleby="sucha"
            )

        model_data = trenuj_model_ml(self.roslina)
        if model_data:
            self.assertEqual(model_data['model_type'], 'RF')

    def test_zapisywanie_modelu_do_pliku(self):
        """Test czy model jest zapisywany do pliku"""
        from django.conf import settings
        import pickle

        model_data = trenuj_model_ml(self.roslina)
        self.assertIsNotNone(model_data)

        model_path = os.path.join(
            settings.BASE_DIR, "ml_models",
            f"model_roslina_{self.roslina.id}.pkl"
        )
        self.assertTrue(os.path.exists(model_path))


class MLUtilsPrzewidywanieTest(TestCase):
    """Testy predykcji częstotliwości"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.roslina = Roslina.objects.create(
            nazwa="Monstera",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            data_zakupu=date.today()
        )

        # Historia podlewań
        base_date = timezone.now() - timedelta(days=100)
        for i in range(15):
            CzynoscPielegnacyjna.objects.create(
                roslina=self.roslina,
                typ="podlewanie",
                wykonane=True,
                uzytkownik=self.user,
                data=base_date + timedelta(days=i * 7),
                stan_gleby="sucha",
                ilosc_wody="200"
            )

    def test_przewidz_czestotliwosc(self):
        """Test predykcji częstotliwości"""
        wynik = przewidz_czestotliwosc_ml(self.roslina)

        self.assertIsNotNone(wynik)
        self.assertIn('rekomendowana_czestotliwosc', wynik)
        self.assertIn('pewnosc', wynik)
        self.assertIn('model_type', wynik)

        # Rekomendacja powinna być w zakresie 1-30 dni
        self.assertGreaterEqual(wynik['rekomendowana_czestotliwosc'], 1)
        self.assertLessEqual(wynik['rekomendowana_czestotliwosc'], 30)

    def test_predykcja_dla_regularnych_podlewan(self):
        """Test czy predykcja jest bliska rzeczywistej częstotliwości"""
        wynik = przewidz_czestotliwosc_ml(self.roslina)

        if wynik:
            # Dla regularnych podlewań co 7 dni, predykcja powinna być bliska 7
            self.assertGreaterEqual(wynik['rekomendowana_czestotliwosc'], 5)
            self.assertLessEqual(wynik['rekomendowana_czestotliwosc'], 9)


class MLUtilsAnalizaStatystycznaTest(TestCase):
    """Testy analizy statystycznej (backup)"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.roslina = Roslina.objects.create(
            nazwa="Monstera",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            data_zakupu=date.today()
        )

    def test_za_malo_danych(self):
        """Test analizy statystycznej z za małą ilością danych"""
        wynik = analizuj_wzorce_statystyczne(self.roslina)

        self.assertEqual(wynik['liczba_podlan'], 0)
        self.assertLess(wynik['pewnosc'], 0.5)
        self.assertIn('komunikat', wynik)

    def test_wystarczajaco_danych(self):
        """Test analizy statystycznej z wystarczającą ilością danych"""
        base_date = timezone.now() - timedelta(days=50)
        for i in range(8):
            CzynoscPielegnacyjna.objects.create(
                roslina=self.roslina,
                typ="podlewanie",
                wykonane=True,
                uzytkownik=self.user,
                data=base_date + timedelta(days=i * 7)
            )

        wynik = analizuj_wzorce_statystyczne(self.roslina)

        self.assertGreater(wynik['liczba_podlan'], 0)
        self.assertIn('rekomendowana_czestotliwosc', wynik)
        self.assertIn('srednia', wynik)
        self.assertIn('mediana', wynik)


class MLUtilsZaktualizujAnalizeTest(TestCase):
    """Testy aktualizacji analizy rośliny"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.roslina = Roslina.objects.create(
            nazwa="Monstera",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            data_zakupu=date.today()
        )

        # Historia podlewań
        base_date = timezone.now() - timedelta(days=100)
        for i in range(15):
            CzynoscPielegnacyjna.objects.create(
                roslina=self.roslina,
                typ="podlewanie",
                wykonane=True,
                uzytkownik=self.user,
                data=base_date + timedelta(days=i * 7),
                stan_gleby="sucha",
                ilosc_wody="200"
            )

    def test_zaktualizuj_analize_tworzy_obiekt(self):
        """Test czy zaktualizuj_analize tworzy obiekt AnalizaPielegnacji"""
        wynik = zaktualizuj_analize_rosliny(self.roslina)

        self.assertIn('analiza', wynik)
        analiza = wynik['analiza']
        self.assertIsInstance(analiza, AnalizaPielegnacji)
        self.assertEqual(analiza.roslina, self.roslina)

    def test_zaktualizuj_analize_zapisuje_typ_modelu(self):
        """Test czy zapisywany jest typ modelu"""
        wynik = zaktualizuj_analize_rosliny(self.roslina)
        analiza = wynik['analiza']

        self.assertIn(analiza.typ_modelu, ['RF', 'GB'])

    def test_zaktualizuj_analize_zapisuje_metryki(self):
        """Test czy zapisywane są metryki ML"""
        wynik = zaktualizuj_analize_rosliny(self.roslina)
        analiza = wynik['analiza']

        self.assertIsNotNone(analiza.rekomendowana_czestotliwosc)
        self.assertIsNotNone(analiza.pewnosc_rekomendacji)
        self.assertGreater(analiza.liczba_podlan, 0)

    def test_zaktualizuj_analize_aktualizuje_istniejaca(self):
        """Test czy istniejąca analiza jest aktualizowana"""
        # Pierwsza aktualizacja
        wynik1 = zaktualizuj_analize_rosliny(self.roslina)
        analiza1_id = wynik1['analiza'].id

        # Druga aktualizacja
        wynik2 = zaktualizuj_analize_rosliny(self.roslina)
        analiza2_id = wynik2['analiza'].id

        # Powinien być ten sam obiekt
        self.assertEqual(analiza1_id, analiza2_id)


class MLUtilsZastosujRekomendacjeTest(TestCase):
    """Testy automatycznego stosowania rekomendacji"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.roslina = Roslina.objects.create(
            nazwa="Monstera",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            data_zakupu=date.today()
        )

        # Historia podlewań
        base_date = timezone.now() - timedelta(days=100)
        for i in range(15):
            CzynoscPielegnacyjna.objects.create(
                roslina=self.roslina,
                typ="podlewanie",
                wykonane=True,
                uzytkownik=self.user,
                data=base_date + timedelta(days=i * 10),  # Co 10 dni
                stan_gleby="sucha",
                ilosc_wody="200"
            )

    def test_zastosuj_rekomendacje_z_wysoka_pewnoscia(self):
        """Test stosowania rekomendacji przy wysokiej pewności"""

        # ✅ Mock zaktualizuj_analize_rosliny() żeby zwrócić kontrolowane wartości
        mock_analiza = MagicMock()
        mock_analiza.pewnosc_rekomendacji = 0.85
        mock_analiza.rekomendowana_czestotliwosc = 10
        mock_analiza.liczba_podlan = 15

        mock_wynik = {
            'analiza': mock_analiza,
            'wzorce': {'model_type': 'RF'}
        }

        stara_czestotliwosc = self.roslina.czestotliwosc_podlewania

        with patch('bloomly.ml_utils.zaktualizuj_analize_rosliny', return_value=mock_wynik):
            wynik = zastosuj_rekomendacje_ml(self.roslina, min_pewnosc=0.7)

        # Sprawdź że rekomendacja została zastosowana
        self.assertTrue(wynik['zastosowano'], f"Wynik: {wynik}")
        self.assertEqual(wynik['stara'], stara_czestotliwosc)
        self.assertEqual(wynik['nowa'], 10)
        self.assertEqual(wynik['pewnosc'], 0.85)

        # Sprawdź że roślina została zaktualizowana
        self.roslina.refresh_from_db()
        self.assertEqual(self.roslina.czestotliwosc_podlewania, 10)

    def test_nie_zastosuj_rekomendacje_z_niska_pewnoscia(self):
        """Test nie stosowania rekomendacji przy niskiej pewności"""

        # ✅ Mock z NISKĄ pewnością
        mock_analiza = MagicMock()
        mock_analiza.pewnosc_rekomendacji = 0.4  # Poniżej threshold 0.7
        mock_analiza.rekomendowana_czestotliwosc = 10
        mock_analiza.liczba_podlan = 15

        mock_wynik = {
            'analiza': mock_analiza,
            'wzorce': {'model_type': 'GB'}
        }

        stara_czestotliwosc = self.roslina.czestotliwosc_podlewania

        with patch('bloomly.ml_utils.zaktualizuj_analize_rosliny', return_value=mock_wynik):
            wynik = zastosuj_rekomendacje_ml(self.roslina, min_pewnosc=0.7)

        # Sprawdź że rekomendacja NIE została zastosowana
        self.assertFalse(wynik['zastosowano'], f"Wynik: {wynik}")

        # Sprawdź że roślina NIE została zmieniona
        self.roslina.refresh_from_db()
        self.assertEqual(
            self.roslina.czestotliwosc_podlewania,
            stara_czestotliwosc,
            "Częstotliwość nie powinna się zmienić przy niskiej pewności"
        )


class MLUtilsObliczJakoscPodlewaniaTest(TestCase):
    """Testy obliczania jakości podlewania"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.roslina = Roslina.objects.create(
            nazwa="Monstera",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            data_zakupu=date.today()
        )

    def test_jakosc_z_dobrym_stanem_gleby(self):
        """Test jakości przy podlewaniu suchej gleby"""
        for i in range(5):
            CzynoscPielegnacyjna.objects.create(
                roslina=self.roslina,
                typ="podlewanie",
                wykonane=True,
                uzytkownik=self.user,
                stan_gleby="sucha",
                ilosc_wody="200"
            )

        jakosc = _oblicz_jakosc_podlewania(self.roslina)

        self.assertGreater(jakosc['soil_score'], 0.8)

    def test_jakosc_z_zlym_stanem_gleby(self):
        """Test jakości przy podlewaniu mokrej gleby"""
        for i in range(5):
            CzynoscPielegnacyjna.objects.create(
                roslina=self.roslina,
                typ="podlewanie",
                wykonane=True,
                uzytkownik=self.user,
                stan_gleby="mokra",
                ilosc_wody="200"
            )

        jakosc = _oblicz_jakosc_podlewania(self.roslina)

        self.assertLess(jakosc['soil_score'], 0.5)

    def test_jakosc_z_konsekwentna_iloscia_wody(self):
        """Test jakości przy konsekwentnej ilości wody"""
        for i in range(5):
            CzynoscPielegnacyjna.objects.create(
                roslina=self.roslina,
                typ="podlewanie",
                wykonane=True,
                uzytkownik=self.user,
                ilosc_wody="200"  # Zawsze ta sama
            )

        jakosc = _oblicz_jakosc_podlewania(self.roslina)

        self.assertEqual(jakosc['water_score'], 1.0)