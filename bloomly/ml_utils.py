import os
import pickle
import logging
from datetime import datetime
import math

import numpy as np
import pandas as pd
from django.utils import timezone
from django.conf import settings
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import cross_val_score, KFold


from .models import CzynoscPielegnacyjna, Roslina, AnalizaPielegnacji

# -----------------------------------
# Konfiguracja
# -----------------------------------
logger = logging.getLogger(__name__)

ML_MODELS_DIR = os.path.join(settings.BASE_DIR, "ml_models")
os.makedirs(ML_MODELS_DIR, exist_ok=True)

# ZMIANA: obniżony próg minimalny dla ML
MIN_SAMPLES_FOR_ML = 6  # było 8 - teraz 6
MIN_R2_FOR_UI = 0.20  # było 0.30 - bardziej tolerancyjne
PRED_MIN, PRED_MAX = 1, 30


# -----------------------------------
# Pomocnicze
# -----------------------------------
def _safe_mean(a):
    a = np.asarray(a, dtype=float)
    return float(np.nanmean(a)) if a.size else 0.0


def _safe_median(a):
    a = np.asarray(a, dtype=float)
    return float(np.nanmedian(a)) if a.size else 0.0


def _month_to_season(m: int) -> int:
    """Mapuje miesiąc (1-12) na porę roku (1-zima, 2-wiosna, 3-lato, 4-jesień)."""
    return (m % 12 + 3) // 3


# --- mapowanie stanu gleby + ilość wody (ml) ---
_SOIL_ALIASES = {
    "sucha": {"sucha", "dry", "0"},
    "ok": {"ok", "umiarkowana", "wilgotna", "normalna", "lekko wilgotna", "moist", "1"},
    "mokra": {"mokra", "wet", "przelana", "2"},
}


def _soil_to_num(val):
    """Zamień różne reprezentacje stanu gleby na {0,1,2} lub NaN."""
    if val is None:
        return math.nan
    s = str(val).strip().lower()
    for k, variants in _SOIL_ALIASES.items():
        if s in variants:
            return {"sucha": 0.0, "ok": 1.0, "mokra": 2.0}[k]
    try:
        x = float(s.replace(",", "."))
        if x in (0.0, 1.0, 2.0):
            return x
    except Exception:
        pass
    return math.nan


def _soil_one_hot(num):
    """One-hot stan gleby: soil_dry/soil_ok/soil_wet (NaN -> wszystkie 0)."""
    if math.isnan(num):
        return {"soil_dry": 0.0, "soil_ok": 0.0, "soil_wet": 0.0}
    return {
        "soil_dry": 1.0 if num == 0 else 0.0,
        "soil_ok": 1.0 if num == 1 else 0.0,
        "soil_wet": 1.0 if num == 2 else 0.0,
    }


# NOWA FUNKCJA: mapowanie ilości wody na kategorię
def _water_category(val):
    """Konwertuje ilość wody na kategorię: low/med/high"""
    if val is None or val == "":
        return None
    s = str(val).strip().lower()

    # Tekstowe wartości
    if s in ["low", "mało", "malo", "niska"]:
        return 0
    elif s in ["med", "medium", "średnio", "srednio", "normalna"]:
        return 1
    elif s in ["high", "dużo", "duzo", "wysoka"]:
        return 2

    # Numeryczne wartości (ml)
    try:
        ml = float(s.replace(",", "."))
        if ml < 100:
            return 0  # mało
        elif ml < 300:
            return 1  # średnio
        else:
            return 2  # dużo
    except Exception:
        pass

    return None


def _water_one_hot(category):
    """One-hot dla ilości wody"""
    if category is None:
        return {"water_low": 0.0, "water_med": 0.0, "water_high": 0.0}
    return {
        "water_low": 1.0 if category == 0 else 0.0,
        "water_med": 1.0 if category == 1 else 0.0,
        "water_high": 1.0 if category == 2 else 0.0,
    }


def _oblicz_pewnosc_regularnosci(interwaly, srednia, odchylenie):
    """
    0..1 – jak bardzo powtarzalne są interwały podlewania.
    ZMIANA: bardziej tolerancyjna formuła
    """
    if not interwaly or srednia <= 0:
        return 0.5

    # Współczynnik zmienności (CV)
    cv = odchylenie / max(srednia, 1e-6)

    # Mapowanie CV na pewność (im mniejszy CV, tym lepiej)
    # CV < 0.3 = bardzo dobre, CV > 1.0 = słabe
    if cv < 0.3:
        pewnosc = 1.0
    elif cv < 0.5:
        pewnosc = 0.85
    elif cv < 0.7:
        pewnosc = 0.7
    elif cv < 1.0:
        pewnosc = 0.55
    else:
        pewnosc = max(0.3, 1.0 - cv * 0.5)

    return max(0.0, min(1.0, pewnosc))


def _oblicz_jakosc_podlewania(roslina: Roslina):
    """
    Zwraca:
      - soil_score:  0..1 (czy podlewasz raczej przy suchej / ok glebie, a nie mokrej)
      - water_score: 0..1 (spójność ilości wody)
    """
    qs = CzynoscPielegnacyjna.objects.filter(
        roslina=roslina,
        typ="podlewanie",
        wykonane=True,
    )

    # --- stan gleby ---
    soils = [getattr(c, "stan_gleby", None) for c in qs if getattr(c, "stan_gleby", None)]
    soil_score = 0.5
    if len(soils) >= 3:
        soil_vals = []
        for s in soils:
            num = _soil_to_num(s)
            if math.isnan(num):
                continue
            if num == 0:  # sucha
                soil_vals.append(1.0)
            elif num == 1:  # ok / wilgotna
                soil_vals.append(0.8)
            else:  # mokra / przelana
                soil_vals.append(0.2)
        if soil_vals:
            soil_score = float(sum(soil_vals)) / len(soil_vals)

    # --- ilość wody (stabilność) ---
    water_cats = []
    for c in qs:
        cat = _water_category(getattr(c, "ilosc_wody", None))
        if cat is not None:
            water_cats.append(cat)

    water_score = 0.5
    if len(water_cats) >= 3:
        # Sprawdź czy użytkownik jest konsekwentny w wyborze ilości
        unique_cats = len(set(water_cats))
        if unique_cats == 1:
            water_score = 1.0  # zawsze ta sama ilość
        elif unique_cats == 2:
            water_score = 0.7  # 2 wartości
        else:
            water_score = 0.5  # różnie

    return {
        "soil_score": soil_score,
        "water_score": water_score,
    }


# -----------------------------------
# NOWA FUNKCJA: Ekstrakcja dodatkowych cech
# -----------------------------------
def _extract_advanced_features(roslina: Roslina, current_date):
    """
    Dodatkowe cechy kontekstowe, które mogą poprawić predykcję:
    - liczba dni od ostatniego podlania
    - trend w ostatnich podlewaniach
    - sezonowość
    """
    podlewania = list(
        CzynoscPielegnacyjna.objects.filter(
            roslina=roslina, typ="podlewanie", wykonane=True
        ).order_by("-data")[:5]  # ostatnie 5 podlań
    )

    features = {}

    # Dni od ostatniego podlewania
    if podlewania:
        last = podlewania[0]
        days_since = (current_date.date() - last.data.date()).days
        features['days_since_last'] = min(days_since, 60)  # cap at 60
    else:
        features['days_since_last'] = 0

    # Trend (czy interwały rosną czy maleją)
    if len(podlewania) >= 3:
        recent_intervals = []
        for i in range(len(podlewania) - 1):
            d = (podlewania[i].data.date() - podlewania[i + 1].data.date()).days
            if 0 < d <= 60:
                recent_intervals.append(d)

        if len(recent_intervals) >= 2:
            # Prosty trend: porównaj ostatni z poprzednim
            if recent_intervals[0] > recent_intervals[-1]:
                features['trend'] = 1.0  # rosnący
            elif recent_intervals[0] < recent_intervals[-1]:
                features['trend'] = -1.0  # malejący
            else:
                features['trend'] = 0.0  # stabilny
        else:
            features['trend'] = 0.0
    else:
        features['trend'] = 0.0

    return features


# -----------------------------------
# Jednowierszowe cechy do inferencji
# -----------------------------------
def _build_one_row_features(roslina: Roslina, dt: timezone.datetime) -> pd.DataFrame:
    """
    ZMIANA: Dodano więcej cech i kategoryczne kodowanie wody
    """
    dow = dt.weekday()
    month = dt.month
    hour = dt.hour
    season = _month_to_season(month)

    # meta rośliny
    kat = roslina.kategoria or "unknown"
    trud = roslina.poziom_trudnosci or "unknown"

    # ostatni wpis podlewania
    last = (
        CzynoscPielegnacyjna.objects.filter(
            roslina=roslina, typ="podlewanie", wykonane=True
        )
        .order_by("-data")
        .first()
    )

    soil_num = _soil_to_num(getattr(last, "stan_gleby", None) if last else None)
    soil_oh = _soil_one_hot(soil_num)

    # ZMIANA: kategoryczne kodowanie wody zamiast ml
    water_cat = _water_category(getattr(last, "ilosc_wody", None) if last else None)
    water_oh = _water_one_hot(water_cat)

    # NOWE: dodatkowe cechy
    advanced = _extract_advanced_features(roslina, dt)

    base = pd.DataFrame(
        [
            {
                "dow": dow,
                "month": month,
                "hour": hour,
                "season": season,
                "kategoria": kat,
                "poziom_trudnosci": trud,
                "roll_mean_3": np.nan,
                "roll_std_3": np.nan,
                "roll_med_3": np.nan,
                "count_intervals": 0,
                "days_since_last": advanced.get('days_since_last', 0),
                "trend": advanced.get('trend', 0.0),
                **soil_oh,
                **water_oh,
            }
        ]
    )

    base = pd.get_dummies(
        base,
        columns=["kategoria", "poziom_trudnosci"],
        dummy_na=False,
    )
    return base


# -----------------------------------
# Przygotowanie danych (features/target)
# -----------------------------------
def przygotuj_dane_treningowe(roslina: Roslina):
    """
    ZMIANA: Dodano więcej cech i outlier detection
    """
    qs = (
        CzynoscPielegnacyjna.objects.filter(
            roslina=roslina, typ="podlewanie", wykonane=True
        )
        .order_by("data")
    )
    podlewania = list(qs)
    if len(podlewania) < MIN_SAMPLES_FOR_ML:
        logger.debug(f"Za mało podlewań dla {roslina.nazwa}: {len(podlewania)}")
        return None

    rows = []
    intervals = []

    for i in range(len(podlewania) - 1):
        cur = podlewania[i]
        nxt = podlewania[i + 1]

        inter = (nxt.data.date() - cur.data.date()).days
        if inter <= 0 or inter > 60:
            continue

        # Rolling interwałów
        if i >= 1:
            hist_intervals = []
            for j in range(1, i + 1):
                d = (podlewania[j].data.date() - podlewania[j - 1].data.date()).days
                if 0 < d <= 60:
                    hist_intervals.append(d)
        else:
            hist_intervals = []

        roll_last_n = hist_intervals[-3:] if len(hist_intervals) >= 1 else []
        roll_mean = _safe_mean(roll_last_n) if roll_last_n else np.nan
        roll_std = float(np.std(roll_last_n)) if len(roll_last_n) > 1 else np.nan
        roll_med = _safe_median(roll_last_n) if roll_last_n else np.nan
        count_ok = len(hist_intervals)

        # cechy czasowe
        dow = cur.data.weekday()
        month = cur.data.month
        hour = cur.data.hour
        season = _month_to_season(month)

        # stan gleby + woda
        soil_num = _soil_to_num(getattr(cur, "stan_gleby", None))
        soil_oh = _soil_one_hot(soil_num)

        water_cat = _water_category(getattr(cur, "ilosc_wody", None))
        water_oh = _water_one_hot(water_cat)

        # meta
        kat = roslina.kategoria or "unknown"
        trud = roslina.poziom_trudnosci or "unknown"

        # NOWE: dni od poprzedniego podlewania
        if i > 0:
            days_since = (cur.data.date() - podlewania[i - 1].data.date()).days
        else:
            days_since = 0

        # NOWE: trend
        if len(hist_intervals) >= 2:
            if hist_intervals[-1] > hist_intervals[0]:
                trend = 1.0
            elif hist_intervals[-1] < hist_intervals[0]:
                trend = -1.0
            else:
                trend = 0.0
        else:
            trend = 0.0

        row = {
            "dow": dow,
            "month": month,
            "hour": hour,
            "season": season,
            "kategoria": kat,
            "poziom_trudnosci": trud,
            "roll_mean_3": roll_mean,
            "roll_std_3": roll_std,
            "roll_med_3": roll_med,
            "count_intervals": count_ok,
            "days_since_last": days_since,
            "trend": trend,
            **soil_oh,
            **water_oh,
        }

        rows.append(row)
        intervals.append(inter)

    if len(rows) < 5:  # było 6, teraz 5
        logger.debug(
            f"Za mało prawidłowych par (t->t+1) dla {roslina.nazwa}: {len(rows)}"
        )
        return None

    X = pd.DataFrame(rows)
    y = pd.Series(intervals, name="interwal")

    # ZMIANA: Usuwanie outlierów (IQR method)
    Q1 = y.quantile(0.25)
    Q3 = y.quantile(0.75)
    IQR = Q3 - Q1
    lower_bound = Q1 - 1.5 * IQR
    upper_bound = Q3 + 1.5 * IQR

    mask = (y >= lower_bound) & (y <= upper_bound)
    X = X[mask]
    y = y[mask]

    if len(X) < 5:
        logger.debug(f"Za mało danych po usunięciu outlierów: {len(X)}")
        return None

    # Wypełnianie braków
    for c in ["roll_mean_3", "roll_std_3", "roll_med_3"]:
        if c in X.columns:
            if X[c].notna().any():
                med = float(X[c].median())
            else:
                med = 0.0
            X[c] = X[c].fillna(med)

    X = pd.get_dummies(
        X,
        columns=["kategoria", "poziom_trudnosci"],
        dummy_na=False,
    )

    return X, y


# -----------------------------------
# ZMIANA: Nowa funkcja treningu z cross-validation
# -----------------------------------
def trenuj_model_ml(roslina: Roslina, use_cv=True):
    """
    Trenuje model z walidacją krzyżową (jeśli use_cv=True)
    """
    data = przygotuj_dane_treningowe(roslina)
    if data is None:
        return None

    X, y = data

    # ZMIANA: wybór modelu na podstawie liczby próbek
    if len(X) < 15:
        # Dla małych zbiorów: prostszy model
        model = GradientBoostingRegressor(
            n_estimators=50,
            max_depth=3,
            learning_rate=0.1,
            min_samples_leaf=2,
            random_state=42,
        )
        model_type = "GB"
        logger.info(f"Używam GradientBoosting dla {roslina.nazwa} ({len(X)} próbek)")
    else:
        # Dla większych zbiorów: Random Forest
        model = RandomForestRegressor(
            n_estimators=200,
            max_depth=6,
            max_features="sqrt",
            min_samples_leaf=2,
            random_state=42,
            n_jobs=-1,
        )
        model_type = "RF"
        logger.info(f"Używam RandomForest dla {roslina.nazwa} ({len(X)} próbek)")

    # ZMIANA: Cross-validation dla małych zbiorów
    if use_cv and len(X) >= 8:
        kf = KFold(n_splits=min(5, len(X)), shuffle=True, random_state=42)
        cv_scores = cross_val_score(
            model, X, y,
            cv=kf,
            scoring='neg_mean_absolute_error',
            n_jobs=-1
        )
        cv_mae = -cv_scores.mean()
        cv_mae_std = cv_scores.std()

        logger.info(
            f"CV dla {roslina.nazwa}: MAE={cv_mae:.2f} ± {cv_mae_std:.2f}"
        )
    else:
        cv_mae = None
        cv_mae_std = None

    # Trening na całym zbiorze
    model.fit(X, y)

    # Ewaluacja
    y_pred = model.predict(X)
    r2 = r2_score(y, y_pred)
    mae = mean_absolute_error(y, y_pred)
    rmse = float(np.sqrt(mean_squared_error(y, y_pred)))

    # ZMIANA: Adjusted R² dla małych zbiorów
    n = len(X)
    p = X.shape[1]
    if n > p + 1:
        adj_r2 = 1 - (1 - r2) * (n - 1) / (n - p - 1)
    else:
        adj_r2 = r2

    raw_med = X.median(numeric_only=True).to_dict()
    feature_medians = {
        k: (0.0 if (isinstance(v, float) and np.isnan(v)) else float(v))
        for k, v in raw_med.items()
    }

    model_path = os.path.join(ML_MODELS_DIR, f"model_roslina_{roslina.id}.pkl")
    model_data = {
        "model": model,
        "feature_columns": list(X.columns),
        "feature_medians": feature_medians,
        "score": float(r2),
        "adj_score": float(adj_r2),
        "mae": float(mae),
        "rmse": float(rmse),
        "cv_mae": float(cv_mae) if cv_mae else None,
        "cv_mae_std": float(cv_mae_std) if cv_mae_std else None,
        "n_samples": int(len(X)),
        "trained_at": datetime.now().isoformat(),
        "model_type": model_type,
    }

    with open(model_path, "wb") as f:
        pickle.dump(model_data, f)

    logger.info(
        f"Model dla {roslina.nazwa}: R²={r2:.3f} (adj={adj_r2:.3f}), "
        f"MAE={mae:.2f}, RMSE={rmse:.2f}, feat={len(X.columns)}"
    )
    return model_data


# -----------------------------------
# Predykcja (inferencja)
# -----------------------------------
def przewidz_czestotliwosc_ml(roslina: Roslina, teraz=None):
    """
    Przewiduje optymalną częstotliwość podlewania używając wytrenowanego modelu.
    """
    if teraz is None:
        teraz = timezone.now()

    model_path = os.path.join(ML_MODELS_DIR, f"model_roslina_{roslina.id}.pkl")

    if not os.path.exists(model_path):
        logger.info(f"Brak modelu dla {roslina.nazwa}, trenowanie...")
        model_data = trenuj_model_ml(roslina)
        if model_data is None:
            logger.warning(f"Nie udało się wytrenować modelu dla {roslina.nazwa}")
            return None
    else:
        try:
            with open(model_path, "rb") as f:
                model_data = pickle.load(f)
        except Exception as e:
            logger.error(f"Błąd ładowania modelu dla {roslina.nazwa}: {e}")
            model_data = trenuj_model_ml(roslina)
            if model_data is None:
                return None

    if model_data.get("n_samples", 0) < MIN_SAMPLES_FOR_ML:
        logger.warning(
            f"Model dla {roslina.nazwa} ma za mało próbek: {model_data.get('n_samples', 0)}"
        )
        return None

    X_pred = _build_one_row_features(roslina, teraz)
    cols = model_data["feature_columns"]
    X_pred = X_pred.reindex(columns=cols)

    med = model_data.get("feature_medians", {})
    for c in X_pred.columns:
        if c in med:
            X_pred[c] = X_pred[c].fillna(med[c])
        else:
            X_pred[c] = X_pred[c].fillna(0.0)

    pred = float(model_data["model"].predict(X_pred)[0])
    pred = int(round(max(PRED_MIN, min(PRED_MAX, pred))))

    # ZMIANA: Użyj adjusted R² jako pewność
    pewnosc = model_data.get("adj_score", model_data.get("score", 0.0))

    logger.info(
        f"Predykcja dla {roslina.nazwa}: {pred} dni "
        f"(R²={pewnosc:.3f}, MAE={model_data.get('mae', 0):.2f})"
    )

    return {
        "rekomendowana_czestotliwosc": pred,
        "pewnosc": pewnosc,
        "r2": model_data.get("adj_score", model_data.get("score", 0.0)),
        "mae": model_data.get("mae", 0.0),
        "rmse": model_data.get("rmse", 0.0),
        "cv_mae": model_data.get("cv_mae"),
        "n_samples": model_data.get("n_samples", 0),
        "model_type": model_data.get("model_type", "RF"),
    }


# -----------------------------------
# Backup statystyczny
# -----------------------------------
def _policz_statystyki_podlewan(roslina):
    """Zwraca: liczba_podlan, interwaly[], srednia, mediana, odchylenie."""
    podlewania = CzynoscPielegnacyjna.objects.filter(
        roslina=roslina, typ='podlewanie', wykonane=True
    ).order_by('data')

    interwaly = []
    lst = list(podlewania)
    for i in range(1, len(lst)):
        d = (lst[i].data.date() - lst[i - 1].data.date()).days
        if 0 < d <= 60:
            interwaly.append(d)

    srednia = _safe_mean(interwaly) if interwaly else 0.0
    mediana = _safe_median(interwaly) if interwaly else 0.0
    odchylenie = float(np.std(interwaly)) if interwaly else 0.0

    return {
        'liczba_podlan': podlewania.count(),
        'interwaly': interwaly,
        'srednia': srednia,
        'mediana': mediana,
        'odchylenie': odchylenie,
    }


def analizuj_wzorce_statystyczne(roslina: Roslina):
    """
    Prosta analiza statystyczna jako backup gdy ML nie ma wystarczających danych.
    """
    qs = (
        CzynoscPielegnacyjna.objects.filter(
            roslina=roslina, typ="podlewanie", wykonane=True
        )
        .order_by("data")
    )
    if qs.count() < 3:
        return {
            "rekomendowana_czestotliwosc": roslina.czestotliwosc_podlewania,
            "pewnosc": 0.3,
            "liczba_podlan": qs.count(),
            "komunikat": "Za mało danych (minimum 3 podlania)",
            "model_type": "Statystyczny",
        }

    interwaly = []
    lst = list(qs)
    for i in range(1, len(lst)):
        d = (lst[i].data.date() - lst[i - 1].data.date()).days
        if 0 < d <= 60:
            interwaly.append(d)

    if len(interwaly) < 2:
        return {
            "rekomendowana_czestotliwosc": roslina.czestotliwosc_podlewania,
            "pewnosc": 0.4,
            "liczba_podlan": qs.count(),
            "komunikat": "Za mało prawidłowych interwałów",
            "model_type": "Statystyczny",
        }

    srednia = _safe_mean(interwaly)
    mediana = _safe_median(interwaly)
    odchylenie = float(np.std(interwaly)) if interwaly else 0.0

    rekomendacja = int(round(0.6 * srednia + 0.4 * mediana))
    rekomendacja = max(PRED_MIN, min(PRED_MAX, rekomendacja))

    reg_score = _oblicz_pewnosc_regularnosci(interwaly, srednia, odchylenie)
    pewnosc = 0.4 + 0.4 * reg_score

    logger.info(
        f"Analiza stat. {roslina.nazwa}: średnia={srednia:.1f}, "
        f"rekomendacja={rekomendacja}, pewność={pewnosc:.2f}"
    )

    return {
        "rekomendowana_czestotliwosc": rekomendacja,
        "pewnosc": round(pewnosc, 2),
        "liczba_podlan": qs.count(),
        "srednia": round(srednia, 1),
        "mediana": mediana,
        "odchylenie": round(odchylenie, 1),
        "interwaly": interwaly,
        "model_type": "Statystyczny",
    }


# -----------------------------------
# Analiza pór podlewania
# -----------------------------------
def analizuj_pory_podlewania(roslina: Roslina):
    """Zlicza pory dnia, kiedy użytkownik najczęściej podlewa."""
    qs = CzynoscPielegnacyjna.objects.filter(
        roslina=roslina, typ="podlewanie", wykonane=True
    )

    rano = popoludniu = wieczorem = noc = 0

    for p in qs:
        h = p.data.hour
        if 6 <= h < 12:
            rano += 1
        elif 12 <= h < 18:
            popoludniu += 1
        elif 18 <= h < 24:
            wieczorem += 1
        else:
            noc += 1

    pory_dict = {"rano": rano, "popoludniu": popoludniu, "wieczorem": wieczorem, "noc": noc}
    preferowana = max(pory_dict.items(), key=lambda x: x[1])[0] if qs.count() > 0 else None

    return {
        "rano": rano,
        "popoludniu": popoludniu,
        "wieczorem": wieczorem,
        "noc": noc,
        "preferowana_pora": preferowana,
    }


# -----------------------------------
# Aktualizacja analizy - POPRAWIONA
# -----------------------------------
def zaktualizuj_analize_rosliny(roslina):
    """
    ZMIANA: Zaktualizowana logika agregacji pewności + zapis nowych pól
    """
    logger.info(f"Aktualizacja analizy dla rośliny: {roslina.nazwa}")

    stat = _policz_statystyki_podlewan(roslina)
    wynik_ml = przewidz_czestotliwosc_ml(roslina)

    if wynik_ml and wynik_ml.get('n_samples', 0) >= MIN_SAMPLES_FOR_ML:
        wzorce = dict(wynik_ml)
        wzorce['komunikat'] = (
            f"Predykcja ML ({wzorce.get('model_type', 'RF')}) oparta na {wynik_ml['n_samples']} próbkach "
            f"(MAE: {wynik_ml.get('mae', 0):.1f} dni)"
        )
        wzorce['liczba_podlan'] = stat['liczba_podlan']
    else:
        wzorce = analizuj_wzorce_statystyczne(roslina)
        logger.info(f"Używam analizy statystycznej dla {roslina.nazwa}")

    # ZMIANA: Bardziej konserwatywna agregacja pewności
    if wynik_ml and wynik_ml.get("n_samples", 0) >= MIN_SAMPLES_FOR_ML and wynik_ml.get("pewnosc", 0) > MIN_R2_FOR_UI:
        pewnosc_modelu = float(wynik_ml.get("pewnosc", 0.5))
    else:
        pewnosc_modelu = float(wzorce.get("pewnosc", 0.5))

    pewnosc_modelu = max(0.0, min(1.0, pewnosc_modelu))

    reg_score = _oblicz_pewnosc_regularnosci(
        stat.get("interwaly") or [],
        stat.get("srednia", 0.0),
        stat.get("odchylenie", 0.0),
    )

    jakosc = _oblicz_jakosc_podlewania(roslina)
    soil_score = jakosc["soil_score"]
    water_score = jakosc["water_score"]
    biome_score = 0.5 * soil_score + 0.5 * water_score

    # ZMIANA: Większa waga dla jakości modelu
    pewnosc_laczna = (
            0.5 * pewnosc_modelu +  # było 0.4
            0.3 * reg_score +  # było 0.35
            0.2 * biome_score  # było 0.25
    )
    pewnosc_laczna = float(max(0.0, min(1.0, pewnosc_laczna)))

    wzorce["pewnosc_modelu"] = round(pewnosc_modelu, 2)
    wzorce["pewnosc_regularnosci"] = round(reg_score, 2)
    wzorce["pewnosc_gleby"] = round(soil_score, 2)
    wzorce["pewnosc_wody"] = round(water_score, 2)
    wzorce["pewnosc_laczna"] = round(pewnosc_laczna, 2)
    wzorce["pewnosc"] = wzorce["pewnosc_laczna"]

    # Zapis do bazy
    analiza, created = AnalizaPielegnacji.objects.get_or_create(
        roslina=roslina, uzytkownik=roslina.wlasciciel
    )

    analiza.srednia_czestotliwosc_dni = stat['srednia'] if stat['srednia'] > 0 else \
        wzorce.get('srednia', wzorce['rekomendowana_czestotliwosc'])
    analiza.odchylenie_standardowe = stat['odchylenie']
    analiza.liczba_podlan = stat['liczba_podlan']

    pory = analizuj_pory_podlewania(roslina)
    analiza.podlewa_rano = pory['rano'] > 0
    analiza.podlewa_po_poludniu = pory['popoludniu'] > 0
    analiza.podlewa_wieczorem = pory['wieczorem'] > 0

    analiza.rekomendowana_czestotliwosc = wzorce['rekomendowana_czestotliwosc']
    analiza.pewnosc_rekomendacji = wzorce.get('pewnosc', 0.5)

    # ✅ NOWE - Zapis typu modelu
    analiza.typ_modelu = wzorce.get('model_type', 'RF')

    # ✅ NOWE - Zapis metryk ML
    analiza.r2_score = wzorce.get('r2', None)
    analiza.mae = wzorce.get('mae', None)
    analiza.rmse = wzorce.get('rmse', None)
    analiza.cv_mae = wzorce.get('cv_mae', None)

    # ✅ NOWE - Składowe pewności
    analiza.pewnosc_model = wzorce.get('pewnosc_modelu', 0.0)
    analiza.pewnosc_regularnosc = wzorce.get('pewnosc_regularnosci', 0.0)
    analiza.pewnosc_biologia = biome_score

    analiza.save()

    logger.info(
        f"Analiza zapisana dla {roslina.nazwa}: "
        f"model={wzorce.get('model_type', 'unknown')} | "
        f"liczba_podlan={analiza.liczba_podlan} | "
        f"rekomendacja={analiza.rekomendowana_czestotliwosc} dni | "
        f"pewność={pewnosc_laczna:.2f}"
    )

    return {'analiza': analiza, 'wzorce': wzorce, 'pory': pory, 'created': created}


def zastosuj_rekomendacje_ml(roslina: Roslina, min_pewnosc: float = 0.5):
    """
    ZMIANA: Obniżony próg pewności do 0.5
    """
    wynik = zaktualizuj_analize_rosliny(roslina)
    analiza = wynik["analiza"]

    if analiza.pewnosc_rekomendacji >= min_pewnosc and analiza.liczba_podlan >= MIN_SAMPLES_FOR_ML:
        stara = roslina.czestotliwosc_podlewania
        roslina.czestotliwosc_podlewania = analiza.rekomendowana_czestotliwosc
        roslina.save()

        logger.info(
            f"Zastosowano rekomendację ML dla {roslina.nazwa}: "
            f"{stara} -> {analiza.rekomendowana_czestotliwosc} dni"
        )
        return {
            "zastosowano": True,
            "stara": stara,
            "nowa": analiza.rekomendowana_czestotliwosc,
            "pewnosc": analiza.pewnosc_rekomendacji,
            "model_type": wynik["wzorce"].get("model_type", "Unknown"),
        }

    logger.info(
        f"Nie zastosowano rekomendacji dla {roslina.nazwa}: "
        f"pewność={analiza.pewnosc_rekomendacji:.2f} < {min_pewnosc} "
        f"lub za mało danych ({analiza.liczba_podlan} podlań)"
    )
    return {
        "zastosowano": False,
        "powod": (
            f"Pewność {analiza.pewnosc_rekomendacji:.2f} < {min_pewnosc} "
            f"lub za mało danych ({analiza.liczba_podlan} podlań)"
        ),
    }


# -----------------------------------
# Operacje wsadowe
# -----------------------------------
def retrenuj_wszystkie_modele():
    """Trenuje/retrenuje modele ML dla wszystkich aktywnych roślin."""
    rosliny = Roslina.objects.filter(is_active=True)
    wytrenowane = 0
    pominiete = 0
    bledy = 0

    logger.info(f"Rozpoczynam trenowanie modeli dla {rosliny.count()} roślin...")

    for r in rosliny:
        try:
            wynik = trenuj_model_ml(r)
            if wynik:
                wytrenowane += 1
                print(
                    f"✓ {r.nazwa}: R²={wynik['score']:.3f} (adj={wynik.get('adj_score', 0):.3f}), "
                    f"MAE={wynik['mae']:.2f} dni, próbki={wynik['n_samples']}"
                )
            else:
                pominiete += 1
                print(f"⚠ {r.nazwa}: Za mało danych")
        except Exception as e:
            bledy += 1
            logger.error(f"Błąd dla {r.nazwa}: {str(e)}", exc_info=True)
            print(f"✗ {r.nazwa}: Błąd - {str(e)}")

    logger.info(
        f"Trenowanie zakończone: wytrenowane={wytrenowane}, "
        f"pominięte={pominiete}, błędy={bledy}"
    )
    return {
        "wytrenowane": wytrenowane,
        "pominiete": pominiete,
        "bledy": bledy,
        "total": rosliny.count(),
    }


def statystyki_modeli():
    """Zwraca statystyki wszystkich wytrenowanych modeli."""
    modele = []
    for filename in os.listdir(ML_MODELS_DIR):
        if filename.endswith(".pkl"):
            filepath = os.path.join(ML_MODELS_DIR, filename)
            try:
                with open(filepath, "rb") as f:
                    model_data = pickle.load(f)
                roslina_id = filename.replace("model_roslina_", "").replace(".pkl", "")
                modele.append(
                    {
                        "roslina_id": roslina_id,
                        "r2_score": model_data.get("score", 0),
                        "adj_r2_score": model_data.get("adj_score", 0),
                        "mae": model_data.get("mae", 0),
                        "rmse": model_data.get("rmse", 0),
                        "cv_mae": model_data.get("cv_mae"),
                        "n_samples": model_data.get("n_samples", 0),
                        "model_type": model_data.get("model_type", "Unknown"),
                        "trained_at": model_data.get("trained_at", "unknown"),
                    }
                )
            except Exception as e:
                logger.error(f"Błąd ładowania modelu {filename}: {e}")
    return modele
