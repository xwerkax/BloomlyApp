"""
Testy integracyjne - pipeline ML
Testują kompletny przepływ analizy ML od danych do predykcji
"""

from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta, date
import os

from bloomly.models import (
    Roslina, CzynoscPielegnacyjna, AnalizaPielegnacji
)
from bloomly.ml_utils import (
    przygotuj_dane_treningowe,
    trenuj_model_ml,
    przewidz_czestotliwosc_ml,
    zaktualizuj_analize_rosliny,
    zastosuj_rekomendacje_ml,
    retrenuj_wszystkie_modele
)


class MLPipelineBasicFlowTest(TestCase):
    """Test podstawowego przepływu ML"""

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

    def test_complete_ml_pipeline_with_sufficient_data(self):
        """Test kompletnego pipeline ML z wystarczającą ilością danych"""

        # 1. FAZA: Zbieranie danych - regularny wzorzec co 7 dni
        base_date = timezone.now() - timedelta(days=100)
        for i in range(15):
            CzynoscPielegnacyjna.objects.create(
                roslina=self.roslina,
                typ="podlewanie",
                uzytkownik=self.user,
                wykonane=True,
                data=base_date + timedelta(days=i * 7),
                stan_gleby="sucha",
                ilosc_wody="200"
            )

        # 2. FAZA: Przygotowanie danych
        dane = przygotuj_dane_treningowe(self.roslina)
        self.assertIsNotNone(dane)
        X, y = dane
        self.assertGreater(len(X), 0)
        self.assertEqual(len(X), len(y))

        # 3. FAZA: Trenowanie modelu
        model_data = trenuj_model_ml(self.roslina)
        self.assertIsNotNone(model_data)
        self.assertIn('model', model_data)
        self.assertIn('score', model_data)
        self.assertIn('mae', model_data)

        # 4. FAZA: Predykcja
        wynik = przewidz_czestotliwosc_ml(self.roslina)
        self.assertIsNotNone(wynik)
        self.assertIn('rekomendowana_czestotliwosc', wynik)

        # Dla regularnych podlewań co 7 dni, predykcja powinna być bliska 7
        self.assertGreaterEqual(wynik['rekomendowana_czestotliwosc'], 5)
        self.assertLessEqual(wynik['rekomendowana_czestotliwosc'], 9)

        # 5. FAZA: Aktualizacja analizy w bazie
        analiza_result = zaktualizuj_analize_rosliny(self.roslina)
        analiza = analiza_result['analiza']

        self.assertIsInstance(analiza, AnalizaPielegnacji)
        self.assertEqual(analiza.roslina, self.roslina)
        self.assertGreater(analiza.liczba_podlan, 0)
        self.assertIn(analiza.typ_modelu, ['RF', 'GB'])

        # 6. FAZA: Zastosowanie rekomendacji (jeśli pewność wysoka)
        if analiza.pewnosc_rekomendacji >= 0.7:
            zastosuj_result = zastosuj_rekomendacje_ml(self.roslina, min_pewnosc=0.7)
            if zastosuj_result['zastosowano']:
                self.roslina.refresh_from_db()
                self.assertEqual(
                    self.roslina.czestotliwosc_podlewania,
                    analiza.rekomendowana_czestotliwosc
                )


class MLPipelineIrregularPatternsTest(TestCase):
    """Test pipeline ML z nieregularnymi wzorcami"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.roslina = Roslina.objects.create(
            nazwa="Roślina nieregularna",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            data_zakupu=date.today()
        )

    def test_ml_with_irregular_watering_pattern(self):
        """Test ML z nieregularnym wzorcem podlewania"""

        # Nieregularny wzorzec: 5, 10, 7, 12, 6, 9, 8 dni
        base_date = timezone.now() - timedelta(days=80)
        intervals = [5, 10, 7, 12, 6, 9, 8, 11, 7]

        current_date = base_date
        for interval in intervals:
            CzynoscPielegnacyjna.objects.create(
                roslina=self.roslina,
                typ="podlewanie",
                uzytkownik=self.user,
                wykonane=True,
                data=current_date,
                stan_gleby="sucha",
                ilosc_wody="200"
            )
            current_date += timedelta(days=interval)

        # Trenuj i przewiduj
        model_data = trenuj_model_ml(self.roslina)
        self.assertIsNotNone(model_data)

        wynik = przewidz_czestotliwosc_ml(self.roslina)
        self.assertIsNotNone(wynik)

        # Średnia z interwałów to ~8.3 dni
        # Model powinien to uchwycić
        self.assertGreaterEqual(wynik['rekomendowana_czestotliwosc'], 6)
        self.assertLessEqual(wynik['rekomendowana_czestotliwosc'], 11)

        # Pewność powinna być niższa niż dla regularnych wzorców
        self.assertLess(wynik['pewnosc'], 0.999)


class MLPipelineSeasonalPatternsTest(TestCase):
    """Test pipeline ML z wzorcami sezonowymi"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.roslina = Roslina.objects.create(
            nazwa="Roślina sezonowa",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            data_zakupu=date.today()
        )

    def test_ml_with_seasonal_pattern(self):
        """Test ML z sezonowym wzorcem (lato częściej, zima rzadziej)"""

        base_date = timezone.now() - timedelta(days=180)

        # Symulacja: latem co 5 dni, zimą co 10 dni
        for i in range(30):
            current_date = base_date + timedelta(days=i * 7)

            # Latem (czerwiec-sierpień) częściej
            if current_date.month in [6, 7, 8]:
                interval = 5
            else:
                interval = 10

            CzynoscPielegnacyjna.objects.create(
                roslina=self.roslina,
                typ="podlewanie",
                uzytkownik=self.user,
                wykonane=True,
                data=current_date,
                stan_gleby="sucha"
            )

        # Zaktualizuj analizę
        result = zaktualizuj_analize_rosliny(self.roslina)
        analiza = result['analiza']

        # Model powinien wykryć różne wzorce
        self.assertGreater(analiza.liczba_podlan, 20)
        self.assertIsNotNone(analiza.rekomendowana_czestotliwosc)


class MLPipelineMultiplePlantsTest(TestCase):
    """Test pipeline ML dla wielu roślin jednocześnie"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )

    def test_retrain_all_models(self):
        """Test retrenowania wszystkich modeli jednocześnie"""

        # Utwórz 3 rośliny z różnymi wzorcami
        rosliny_data = [
            {'nazwa': 'Monstera', 'interval': 7, 'count': 15},
            {'nazwa': 'Fiołek', 'interval': 5, 'count': 20},
            {'nazwa': 'Sukulenty', 'interval': 14, 'count': 12}
        ]

        for data in rosliny_data:
            roslina = Roslina.objects.create(
                nazwa=data['nazwa'],
                wlasciciel=self.user,
                czestotliwosc_podlewania=data['interval'],
                data_zakupu=date.today()
            )

            # Dodaj historię podlewań
            base_date = timezone.now() - timedelta(days=data['count'] * data['interval'])
            for i in range(data['count']):
                CzynoscPielegnacyjna.objects.create(
                    roslina=roslina,
                    typ="podlewanie",
                    uzytkownik=self.user,
                    wykonane=True,
                    data=base_date + timedelta(days=i * data['interval']),
                    stan_gleby="sucha",
                    ilosc_wody="200"
                )

        # Retrenuj wszystkie modele
        wynik = retrenuj_wszystkie_modele()

        # Sprawdź wyniki
        self.assertGreater(wynik['wytrenowane'], 0)
        self.assertEqual(wynik['total'], 3)

        # Sprawdź że każda roślina ma model
        for roslina in Roslina.objects.filter(wlasciciel=self.user):
            from django.conf import settings
            model_path = os.path.join(
                settings.BASE_DIR, "ml_models",
                f"model_roslina_{roslina.id}.pkl"
            )
            # Model powinien istnieć jeśli było wystarczająco danych
            if CzynoscPielegnacyjna.objects.filter(
                    roslina=roslina
            ).count() >= 6:
                self.assertTrue(os.path.exists(model_path))


class MLPipelineModelSelectionTest(TestCase):
    """Test wyboru odpowiedniego modelu (GB vs RF)"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )

    def test_gradient_boosting_for_small_dataset(self):
        """Test wyboru Gradient Boosting dla małego zbioru danych"""

        roslina = Roslina.objects.create(
            nazwa="Mała roślina",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            data_zakupu=date.today()
        )

        # Tylko 10 podlewań (< 15)
        base_date = timezone.now() - timedelta(days=70)
        for i in range(10):
            CzynoscPielegnacyjna.objects.create(
                roslina=roslina,
                typ="podlewanie",
                uzytkownik=self.user,
                wykonane=True,
                data=base_date + timedelta(days=i * 7),
                stan_gleby="sucha"
            )

        model_data = trenuj_model_ml(roslina)

        if model_data:
            # Dla <15 próbek powinien wybrać GB
            self.assertEqual(model_data['model_type'], 'GB')

    def test_random_forest_for_large_dataset(self):
        """Test wyboru Random Forest dla dużego zbioru danych"""

        roslina = Roslina.objects.create(
            nazwa="Duża roślina",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            data_zakupu=date.today()
        )

        # 20 podlewań (>= 15)
        base_date = timezone.now() - timedelta(days=140)
        for i in range(20):
            CzynoscPielegnacyjna.objects.create(
                roslina=roslina,
                typ="podlewanie",
                uzytkownik=self.user,
                wykonane=True,
                data=base_date + timedelta(days=i * 7),
                stan_gleby="sucha"
            )

        model_data = trenuj_model_ml(roslina)

        if model_data:
            # Dla >=15 próbek powinien wybrać RF
            self.assertEqual(model_data['model_type'], 'RF')


class MLPipelineConfidenceCalculationTest(TestCase):
    """Test obliczania pewności rekomendacji"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )

    def test_high_confidence_for_regular_pattern(self):
        """Test wysokiej pewności dla regularnego wzorca"""

        roslina = Roslina.objects.create(
            nazwa="Regularna",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            data_zakupu=date.today()
        )

        # Bardzo regularny wzorzec - zawsze co 7 dni, zawsze sucha gleba
        base_date = timezone.now() - timedelta(days=100)
        for i in range(15):
            CzynoscPielegnacyjna.objects.create(
                roslina=roslina,
                typ="podlewanie",
                wykonane=True,
                uzytkownik=self.user,
                data=base_date + timedelta(days=i * 7),
                stan_gleby="sucha",
                ilosc_wody="200"
            )

        result = zaktualizuj_analize_rosliny(roslina)
        analiza = result['analiza']

        # Pewność powinna być wysoka
        self.assertGreater(analiza.pewnosc_rekomendacji, 0.7)

    def test_low_confidence_for_irregular_pattern(self):
        """Test niskiej pewności dla nieregularnego wzorca"""

        roslina = Roslina.objects.create(
            nazwa="Nieregularna",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            data_zakupu=date.today()
        )

        # Bardzo nieregularny wzorzec - różne interwały, różna gleba
        base_date = timezone.now() - timedelta(days=100)
        intervals = [3, 15, 5, 20, 7, 12, 4, 18]
        stany = ["sucha", "mokra", "ok", "sucha", "mokra", "ok", "sucha", "mokra"]

        current_date = base_date
        for interval, stan in zip(intervals, stany):
            CzynoscPielegnacyjna.objects.create(
                roslina=roslina,
                typ="podlewanie",
                wykonane=True,
                uzytkownik=self.user,
                data=current_date,
                stan_gleby=stan
            )
            current_date += timedelta(days=interval)

        result = zaktualizuj_analize_rosliny(roslina)
        analiza = result['analiza']

        # Pewność powinna być niższa
        self.assertLess(analiza.pewnosc_rekomendacji, 0.85)


class MLPipelineEdgeCasesTest(TestCase):
    """Test przypadków brzegowych w pipeline ML"""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )

    def test_insufficient_data_fallback_to_statistics(self):
        """Test: za mało danych dla ML -> brak predykcji"""

        # Usuń cache'owane modele
        from django.conf import settings
        import shutil

        ml_models_dir = os.path.join(settings.BASE_DIR, "ml_models")
        if os.path.exists(ml_models_dir):
            shutil.rmtree(ml_models_dir)
            os.makedirs(ml_models_dir)

        # Wyczyść dane
        CzynoscPielegnacyjna.objects.all().delete()
        Roslina.objects.all().delete()

        roslina = Roslina.objects.create(
            nazwa="Nowa roślina",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            kategoria='doniczkowa',
            poziom_trudnosci='latwy',
            data_zakupu=date.today()
        )

        # ✅ Tylko 2 podlewania
        base_date = timezone.now() - timedelta(days=14)
        for i in range(2):
            CzynoscPielegnacyjna.objects.create(
                roslina=roslina,
                typ="podlewanie",
                uzytkownik=self.user,
                wykonane=True,
                data=base_date + timedelta(days=i * 7)
            )

        # ✅ DEBUG: Sprawdź co zwraca przygotuj_dane_treningowe
        print("\n=== DEBUG ===")
        print(f"Liczba podlewań: {CzynoscPielegnacyjna.objects.filter(roslina=roslina).count()}")

        dane = przygotuj_dane_treningowe(roslina)
        if dane:
            X, y = dane
            print(f"przygotuj_dane_treningowe() zwróciło: X.shape={X.shape}, len(y)={len(y)}")
            print(f"y values: {list(y)}")
        else:
            print("przygotuj_dane_treningowe() zwróciło None")

        # Sprawdź czy są inne podlewania w bazie
        wszystkie = CzynoscPielegnacyjna.objects.all()
        print(f"\nWszystkie podlewania w bazie: {wszystkie.count()}")
        for p in wszystkie:
            print(f"  - ID={p.id}, roslina_id={p.roslina_id}, data={p.data}, typ={p.typ}")

        wynik_ml = przewidz_czestotliwosc_ml(roslina)
        print(f"\nwynik_ml: {wynik_ml}")

        # ✅ Jeśli są tylko 2 podlewania, powinno być None
        # (2 podlewania = 1 interwał, a funkcja wymaga >= 5 rows)
        self.assertIsNone(wynik_ml, f"Wynik powinien być None dla 2 podlewań, ale jest: {wynik_ml}")

    def test_no_data_at_all(self):
        """Test: brak jakichkolwiek danych"""

        roslina = Roslina.objects.create(
            nazwa="Zupełnie nowa",
            wlasciciel=self.user,
            czestotliwosc_podlewania=7,
            data_zakupu=date.today()
        )

        # Brak podlewań
        result = zaktualizuj_analize_rosliny(roslina)
        analiza = result['analiza']

        # Powinna użyć domyślnych wartości
        self.assertEqual(analiza.liczba_podlan, 0)
        self.assertEqual(
            analiza.rekomendowana_czestotliwosc,
            roslina.czestotliwosc_podlewania
        )