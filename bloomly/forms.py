from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone
from .models import (
    ProfilUzytkownika,
    Roslina,
    CzynoscPielegnacyjna,
    Post,
    Komentarz,
    BazaRoslin,
    Kategoria,
)


# -----------------------------
# Rejestracja / Profil
# -----------------------------
class RejestracjaForm(UserCreationForm):
    # Dodatkowe pola do rejestracji
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "twoj@email.com"}),
    )
    imie = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Twoje imię"}),
    )
    nazwisko = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Twoje nazwisko"}),
    )

    class Meta:
        model = User
        fields = ("username", "imie", "nazwisko", "email", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Bootstrap dla pól
        self.fields["username"].widget.attrs.update({"class": "form-control", "placeholder": "Nazwa użytkownika"})
        self.fields["password1"].widget.attrs.update({"class": "form-control", "placeholder": "Hasło"})
        self.fields["password2"].widget.attrs.update({"class": "form-control", "placeholder": "Powtórz hasło"})

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.first_name = self.cleaned_data["imie"]
        user.last_name = self.cleaned_data["nazwisko"]
        if commit:
            user.save()
        return user


class ProfilForm(forms.ModelForm):

    data_urodzenia = forms.DateField(
        required=False,
        input_formats=["%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%Y.%m.%d"],
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        label="Data urodzenia",
    )
    class Meta:
        model = ProfilUzytkownika
        fields = ['telefon', 'data_urodzenia', 'powiadomienia_email', 'biogram']
        widgets = {
            'data_urodzenia': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'telefon': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+48 123 456 789'}),
            'biogram': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Napisz kilka słów o sobie (max 600 znaków)…'}),
        }
# -----------------------------
# Rośliny / Czynności
# -----------------------------
class RoslinaForm(forms.ModelForm):
    class Meta:
        model = Roslina
        fields = [
            "nazwa",
            "gatunek",
            "kategoria",
            "poziom_trudnosci",
            "data_zakupu",
            "lokalizacja",
            "notatki",
            "zdjecie",
            "czestotliwosc_podlewania",
            "ostatnie_podlewanie",
        ]
        widgets = {
            "nazwa": forms.TextInput(attrs={"class": "form-control", "placeholder": "np. Moja ukochana monstera"}),
            "gatunek": forms.TextInput(attrs={"class": "form-control", "placeholder": "np. Monstera deliciosa"}),
            "kategoria": forms.Select(attrs={"class": "form-select"}),
            "poziom_trudnosci": forms.Select(attrs={"class": "form-select"}),
            "data_zakupu": forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }, format='%Y-%m-%d'),
            "ostatnie_podlewanie": forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }, format='%Y-%m-%d'),
            "lokalizacja": forms.TextInput(attrs={"class": "form-control", "placeholder": "np. salon, balkon"}),
            "notatki": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Dodatkowe informacje..."}),
            "czestotliwosc_podlewania": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 30}),
            "zdjecie": forms.FileInput(attrs={"class": "form-control"}),
        }

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            # Ustaw format daty dla istniejących wartości
            if self.instance and self.instance.pk:
                if self.instance.data_zakupu:
                    self.initial['data_zakupu'] = self.instance.data_zakupu.strftime('%Y-%m-%d')
                if self.instance.ostatnie_podlewanie:
                    self.initial['ostatnie_podlewanie'] = self.instance.ostatnie_podlewanie.strftime('%Y-%m-%d')


class CzynoscForm(forms.ModelForm):
    class Meta:
        model = CzynoscPielegnacyjna
        fields = ["typ", "data", "notatki", "zdjecie"]
        widgets = {
            "typ": forms.Select(attrs={"class": "form-select"}),
            "data": forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}),
            "notatki": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Dodatkowe notatki..."}),
            "zdjecie": forms.FileInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Ustaw domyślną datę na teraz
        if not self.instance.pk:
            self.fields["data"].initial = timezone.now()


class PodlewanieForm(forms.ModelForm):
    class Meta:
        model = CzynoscPielegnacyjna
        # roślinę, użytkownika i typ ustawimy w widoku
        fields = ["data", "stan_gleby", "ilosc_wody", "notatki"]
        widgets = {
            "data": forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}),
            "notatki": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Opcjonalne notatki..."}),
        }
        labels = {
            "data": "Data podlewania",
            "stan_gleby": "Stan gleby",
            "ilosc_wody": "Ilość wody",
            "notatki": "Notatki",
        }

    # domyślna wartość „teraz”
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.initial.get("data"):
            self.initial["data"] = timezone.now().replace(microsecond=0)

class WykonajPrzypomnienieForm(forms.Form):
    data = forms.DateTimeField(
        initial=lambda: timezone.now().replace(microsecond=0, second=0),
        widget=forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}),
        label="Data i godzina wykonania",
    )
    stan_gleby = forms.ChoiceField(
        required=False,
        choices=[("dry","sucha"), ("moist","lekko wilgotna"), ("wet","mokra")],
        widget=forms.Select(attrs={"class": "form-control"}),
        label="Stan gleby",
    )
    ilosc_wody = forms.ChoiceField(
        required=False,
        choices=[("low","mało"), ("med","średnio"), ("high","dużo")],
        widget=forms.Select(attrs={"class": "form-control"}),
        label="Ilość wody",
    )
    notatki = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Opcjonalne uwagi..."}),
        label="Notatki",
    )

    def clean_data(self):
        dt = self.cleaned_data["data"]
        from django.utils import timezone
        # opcjonalna walidacja: nie pozwalaj na przyszłość
        # if dt > timezone.now():
        #     raise forms.ValidationError("Data nie może być w przyszłości.")
        return dt

# -----------------------------
# Forum / Baza wiedzy
# -----------------------------
class PostForm(forms.ModelForm):
    """
    Wybór kategorii uporządkowany w <optgroup>:
    - nagłówek = kategoria główna
    - pozycje: najpierw sama kategoria główna (—), potem jej podkategorie (↳)
    """
    kategoria = forms.ModelChoiceField(
        queryset=Kategoria.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Kategoria",
        empty_label=None,
    )

    class Meta:
        model = Post
        fields = ["tytul", "kategoria", "tresc"]
        widgets = {
            "tytul": forms.TextInput(attrs={"class": "form-control", "placeholder": "Tytuł posta..."}),
            "tresc": forms.Textarea(attrs={"class": "form-control", "rows": 10, "placeholder": "Treść Twojego posta..."}),
        }
        labels = {"tytul": "Tytuł", "tresc": "Treść"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 1) Pobierz aktywne kategorie forum
        main_qs = Kategoria.objects.filter(
            typ="forum", aktywna=True, rodzic__isnull=True
        ).order_by("nazwa")
        sub_qs_all = Kategoria.objects.filter(
            typ="forum", aktywna=True, rodzic__isnull=False
        )

        # 2) Zbuduj choices z optgroups
        choices = []
        for parent in main_qs:
            group = [(parent.pk, f"— {parent.nazwa}")]
            children = sub_qs_all.filter(rodzic=parent).order_by("nazwa")
            group += [(child.pk, f"↳ {child.nazwa}") for child in children]
            choices.append((parent.nazwa, group))
        self.fields["kategoria"].choices = choices

        # 3) BARDZO WAŻNE: ustaw queryset do walidacji (rodzice + dzieci)
        self.fields["kategoria"].queryset = Kategoria.objects.filter(
            typ="forum", aktywna=True
        )

        # (opcjonalnie) initial przy edycji
        if self.instance and getattr(self.instance, "kategoria_id", None):
            self.fields["kategoria"].initial = self.instance.kategoria_id


class KomentarzForm(forms.ModelForm):
    class Meta:
        model = Komentarz
        fields = ["tresc"]
        widgets = {
            "tresc": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Napisz komentarz..."}),
        }


class BazaRoslinForm(forms.ModelForm):
    class Meta:
        model = BazaRoslin
        fields = [
            "nazwa_polska",
            "nazwa_naukowa",
            "rodzina",
            "rodzaj",
            "opis_krotki",
            "opis_szczegolowy",
            "poziom_trudnosci",
            "wymagania_swiatla",
            "czestotliwosc_podlewania",
            "wilgotnosc_powietrza",
            "temperatura_min",
            "temperatura_max",
            "podloz",
            "nawozenie",
            "rozmnazanie",
            "choroby_szkodniki",
            "ciekawostki",
            "toksyczna_dla_ludzi",
            "toksyczna_dla_zwierzat",
            "zdjecie_glowne",
        ]
    # widgets jak w Twojej wersji:
        widgets = {
            "nazwa_polska": forms.TextInput(attrs={"class": "form-control"}),
            "nazwa_naukowa": forms.TextInput(attrs={"class": "form-control"}),
            "rodzina": forms.TextInput(attrs={"class": "form-control"}),
            "rodzaj": forms.TextInput(attrs={"class": "form-control"}),
            "opis_krotki": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "opis_szczegolowy": forms.Textarea(attrs={"class": "form-control", "rows": 6}),
            "poziom_trudnosci": forms.Select(attrs={"class": "form-select"}),
            "wymagania_swiatla": forms.TextInput(attrs={"class": "form-control"}),
            "czestotliwosc_podlewania": forms.TextInput(attrs={"class": "form-control"}),
            "wilgotnosc_powietrza": forms.TextInput(attrs={"class": "form-control"}),
            "temperatura_min": forms.NumberInput(attrs={"class": "form-control"}),
            "temperatura_max": forms.NumberInput(attrs={"class": "form-control"}),
            "podloz": forms.TextInput(attrs={"class": "form-control"}),
            "nawozenie": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "rozmnazanie": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "choroby_szkodniki": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "ciekawostki": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "toksyczna_dla_ludzi": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "toksyczna_dla_zwierzat": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "zdjecie_glowne": forms.FileInput(attrs={"class": "form-control"}),
        }


class WyszukiwarkaRoslinForm(forms.Form):
    query = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Szukaj po nazwie..."}),
        label="Wyszukaj",
    )
    poziom_trudnosci = forms.ChoiceField(
        required=False,
        choices=[("", "Wszystkie poziomy")] + BazaRoslin.POZIOMY_TRUDNOSCI,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Poziom trudności",
    )
    toksyczna = forms.ChoiceField(
        required=False,
        choices=[("", "Wszystkie"), ("bezpieczna", "Tylko bezpieczne"), ("toksyczna", "Tylko toksyczne")],
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Toksyczność",
    )
    sortowanie = forms.ChoiceField(
        required=False,
        choices=[("nazwa_polska", "Nazwa A-Z"), ("-nazwa_polska", "Nazwa Z-A"), ("-created_at", "Najnowsze")],
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Sortuj",
    )
