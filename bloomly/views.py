import logging
from typing import Optional
from datetime import date, datetime, time, timedelta
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, F
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.http import require_GET, require_POST
from django.contrib import messages
from django.contrib.auth.models import User



# Modele
from .models import (
    ProfilUzytkownika,
    Roslina,
    CzynoscPielegnacyjna,
    Przypomnienie,
    Post,
    Komentarz,
    BazaRoslin,
    Kategoria,
    AnalizaPielegnacji,
)

# Formularze
from .forms import (
    RejestracjaForm,
    ProfilForm,
    RoslinaForm,
    CzynoscForm,
    PodlewanieForm,
    PostForm,
    KomentarzForm,
    BazaRoslinForm,
    WyszukiwarkaRoslinForm,
    WykonajPrzypomnienieForm,
)

# ML Utils
from .ml_utils import zaktualizuj_analize_rosliny

logger = logging.getLogger(__name__)


# ============================================
# STRONA GŁÓWNA
# ============================================

def strona_glowna(request):
    """Strona główna - dashboard użytkownika"""
    if request.user.is_authenticated:
        # Statystyki dla zalogowanego użytkownika
        rosliny = Roslina.objects.filter(wlasciciel=request.user, is_active=True)
        rosliny_do_podlania = [r for r in rosliny if r.czy_potrzebuje_podlewania()]
        ostatnie_czynnosci = CzynoscPielegnacyjna.objects.filter(
            uzytkownik=request.user
        ).order_by('-data')[:5]

        # Przypomnienia
        pilne_przypomnienia = Przypomnienie.objects.filter(
            uzytkownik=request.user,
            status__in=['oczekujace', 'wyslane'],
            data_przypomnienia__lte=timezone.now() + timedelta(hours=24)
        ).order_by('data_przypomnienia')[:5]

        context = {
            'liczba_roslin': rosliny.count(),
            'rosliny_do_podlania': len(rosliny_do_podlania),
            'ostatnie_czynnosci': ostatnie_czynnosci,
            'pilne_przypomnienia': pilne_przypomnienia,
        }
    else:
        context = {}

    return render(request, 'bloomly/index.html', context)


# ============================================
# UŻYTKOWNICY - REJESTRACJA I PROFIL
# ============================================

def rejestracja(request):
    """Rejestracja nowego użytkownika"""
    if request.method == 'POST':
        form = RejestracjaForm(request.POST)
        if form.is_valid():
            user = form.save()
            username = form.cleaned_data.get('username')
            messages.success(request, f'Konto zostało utworzone dla {username}! Możesz się teraz zalogować.')
            return redirect('login')
    else:
        form = RejestracjaForm()
    return render(request, 'registration/rejestracja.html', {'form': form})


@login_required
def profil(request):
    """Edycja profilu użytkownika + danych User"""
    profil = getattr(request.user, "profiluzytkownika", None)
    if profil is None:
        from .models import ProfilUzytkownika
        profil = ProfilUzytkownika.objects.create(user=request.user)

    if request.method == "POST":
        form = ProfilForm(request.POST, request.FILES, instance=profil)

        # Pobierz dane z formularza
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()

        # Walidacja username (unikalność)
        if username and username != request.user.username:
            if User.objects.filter(username=username).exists():
                messages.error(request, f"Nazwa użytkownika '{username}' jest już zajęta.")
                return render(request, "bloomly/profil.html", {"form": form, "profil": profil})

        # Walidacja email (unikalność)
        if email and email != request.user.email:
            if User.objects.filter(email=email).exists():
                messages.error(request, f"Email '{email}' jest już używany przez inne konto.")
                return render(request, "bloomly/profil.html", {"form": form, "profil": profil})

        # Zapisz dane User
        if username:
            request.user.username = username
        if email:
            request.user.email = email
        request.user.first_name = first_name
        request.user.last_name = last_name

        # Zapisz profil
        if form.is_valid():
            form.save()
            request.user.save()
            messages.success(request, "✅ Profil został zaktualizowany pomyślnie!")
            return redirect("profil")
        else:
            messages.error(request, "❌ Popraw błędy w formularzu.")
    else:
        form = ProfilForm(instance=profil)

    return render(request, "bloomly/profil.html", {"form": form, "profil": profil})
# ============================================
# ROŚLINY - CRUD
# ============================================

@login_required
def lista_roslin(request):
    """Lista wszystkich roślin użytkownika"""
    rosliny = Roslina.objects.filter(wlasciciel=request.user, is_active=True)

    # Wyszukiwanie
    search = request.GET.get('search')
    if search:
        rosliny = rosliny.filter(
            Q(nazwa__icontains=search) | Q(gatunek__icontains=search)
        )

    context = {
        'rosliny': rosliny,
        'search': search,
    }
    return render(request, 'bloomly/lista_roslin.html', context)


@login_required
def dodaj_roslina(request):
    """Dodawanie nowej rośliny"""
    if request.method == 'POST':
        form = RoslinaForm(request.POST, request.FILES)
        if form.is_valid():
            roslina = form.save(commit=False)
            roslina.wlasciciel = request.user
            roslina.save()
            messages.success(request, f'Roslina "{roslina.nazwa}" zostala dodana!')
            return redirect('lista_roslin')
    else:
        form = RoslinaForm()

    return render(request, 'bloomly/dodaj_roslina.html', {'form': form})


def _days_since(d):
    if not d:
        return None
    if isinstance(d, datetime):
        d = d.date()
    return (date.today() - d).days


@login_required
def szczegoly_rosliny(request, id):
    roslina = get_object_or_404(Roslina, pk=id, wlasciciel=request.user)

    # Historia pielęgnacji
    historia = (
        CzynoscPielegnacyjna.objects
        .filter(roslina=roslina)
        .order_by("-data")
    )

    dni_od_ostatniego = _days_since(roslina.ostatnie_podlewanie)
    freq = roslina.czestotliwosc_podlewania or 7
    niedawno_podlana = (dni_od_ostatniego is not None) and (dni_od_ostatniego < freq)
    do_podlania = (dni_od_ostatniego is None) or (dni_od_ostatniego >= freq)

    return render(request, "bloomly/szczegoly_rosliny.html", {
        "roslina": roslina,
        "historia": historia,
        "czynnosci": historia,
        "dni_od_ostatniego": dni_od_ostatniego,
        "niedawno_podlana": niedawno_podlana,
        "do_podlania": do_podlania,
        "freq": freq,
    })


@login_required
def edytuj_roslina(request, id):
    """Edycja rośliny"""
    roslina = get_object_or_404(Roslina, id=id, wlasciciel=request.user)

    if request.method == 'POST':
        form = RoslinaForm(request.POST, request.FILES, instance=roslina)
        if form.is_valid():
            form.save()
            messages.success(request, f'Roslina "{roslina.nazwa}" zostala zaktualizowana!')
            return redirect('szczegoly_rosliny', id=roslina.id)
    else:
        form = RoslinaForm(instance=roslina)

    context = {
        'form': form,
        'roslina': roslina,
    }
    return render(request, 'bloomly/edytuj_roslina.html', context)


@login_required
def usun_roslina(request, id):
    """Usuwanie rośliny"""
    roslina = get_object_or_404(Roslina, id=id, wlasciciel=request.user)

    if request.method == 'POST':
        nazwa = roslina.nazwa
        roslina.delete()
        messages.success(request, f'Roslina "{nazwa}" zostala usunieta.')
        return redirect('lista_roslin')

    return render(request, 'bloomly/usun_roslina.html', {'roslina': roslina})


# ============================================
# PIELĘGNACJA - PODLEWANIE I CZYNNOŚCI
# ============================================

@login_required
def podlej_roslina(request, id):
    """Ręczne podlewanie rośliny (formularz)"""
    roslina = get_object_or_404(Roslina, id=id, wlasciciel=request.user)

    if request.method == 'POST':
        form = PodlewanieForm(request.POST)
        if form.is_valid():
            ev = form.save(commit=False)
            ev.roslina = roslina
            ev.uzytkownik = request.user
            ev.typ = 'podlewanie'
            ev.wykonane = True
            if not ev.data:
                ev.data = timezone.now()
            ev.save()

            # ONE-OPEN - odśwież przypomnienie
            try:
                from .models import utworz_przypomnienie_podlewanie
                nowe_przyp = utworz_przypomnienie_podlewanie(roslina)
                if nowe_przyp:
                    logger.info(f"Utworzono nowe przypomnienie dla {roslina.nazwa} na {nowe_przyp.data_przypomnienia}")
            except Exception as e:
                logger.error(f"Błąd tworzenia przypomnienia po podlewaniu: {e}")

            # Aktualizacja analizy ML
            try:
                liczba_podlan = CzynoscPielegnacyjna.objects.filter(
                    roslina=roslina, typ='podlewanie', wykonane=True
                ).count()
                if liczba_podlan >= 5:
                    zaktualizuj_analize_rosliny(roslina)
                    logger.info(f"Zaktualizowano analizę ML dla {roslina.nazwa}")
                else:
                    logger.debug(f"Za mało danych dla ML ({liczba_podlan} podlań) - {roslina.nazwa}")
            except Exception as e:
                logger.error(f"Błąd aktualizacji ML dla {roslina.nazwa}: {e}")

            messages.success(request, f'Podlewanie rosliny "{roslina.nazwa}" zostalo zapisane! 💧')
            return redirect('szczegoly_rosliny', id=roslina.id)
    else:
        form = PodlewanieForm()

    return render(request, 'bloomly/podlej_roslina.html', {'form': form, 'roslina': roslina})


@login_required
def dodaj_czynnosc(request, id):
    """Dodawanie dowolnej czynności pielęgnacyjnej"""
    roslina = get_object_or_404(Roslina, id=id, wlasciciel=request.user)

    if request.method == "POST":
        form = CzynoscForm(request.POST, request.FILES)
        if form.is_valid():
            ev = form.save(commit=False)
            ev.roslina = roslina
            ev.uzytkownik = request.user

            if ev.wykonane is None:
                ev.wykonane = True

            if not ev.data:
                ev.data = timezone.now()

            ev.save()

            # Dodatkowa logika tylko dla podlewania
            if ev.typ == "podlewanie":
                # ONE-OPEN - odśwież przypomnienie
                try:
                    from .models import utworz_przypomnienie_podlewanie
                    nowe_przyp = utworz_przypomnienie_podlewanie(roslina)
                    if nowe_przyp:
                        logger.info(
                            f"Utworzono nowe przypomnienie dla {roslina.nazwa} na {nowe_przyp.data_przypomnienia}")
                except Exception as e:
                    logger.error(f"Błąd tworzenia przypomnienia: {e}")

                # Aktualizacja analizy ML
                try:
                    liczba_podlan = CzynoscPielegnacyjna.objects.filter(
                        roslina=roslina,
                        typ="podlewanie",
                        wykonane=True,
                    ).count()
                    if liczba_podlan >= 5:
                        zaktualizuj_analize_rosliny(roslina)
                except Exception as e:
                    logger.error(f"Błąd aktualizacji ML po dodaniu czynności podlewania: {e}")

            messages.success(
                request,
                f'Czynnosc pielegnacyjna dla "{roslina.nazwa}" zostala zapisana.'
            )
            return redirect("szczegoly_rosliny", id=roslina.id)
    else:
        form = CzynoscForm()

    return render(
        request,
        "bloomly/dodaj_czynnosc.html",
        {
            "form": form,
            "roslina": roslina,
        },
    )


@login_required
def oznacz_podlanie(request, id):
    """Szybkie oznaczenie podlania (AJAX/POST endpoint)"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Tylko POST'}, status=405)

    roslina = get_object_or_404(Roslina, id=id, wlasciciel=request.user)

    try:
        # Utwórz czynność podlewania
        czynnosc = CzynoscPielegnacyjna.objects.create(
            roslina=roslina,
            uzytkownik=request.user,
            typ='podlewanie',
            data=timezone.now(),
            wykonane=True,
            notatki="Szybkie podlanie"
        )

        # Aktualizuj datę ostatniego podlewania
        roslina.ostatnie_podlewanie = timezone.now().date()
        roslina.save()

        # Aktualizuj analizę ML
        liczba_podlan = CzynoscPielegnacyjna.objects.filter(
            roslina=roslina,
            typ='podlewanie',
            wykonane=True
        ).count()

        ml_zaktualizowane = False
        if liczba_podlan >= 5:
            try:
                zaktualizuj_analize_rosliny(roslina)
                ml_zaktualizowane = True
                logger.info(f"ML zaktualizowane dla {roslina.nazwa} po podlaniu")
            except Exception as e:
                logger.error(f"Błąd ML: {e}")

        # ONE-OPEN - odśwież przypomnienie
        try:
            from .models import utworz_przypomnienie_podlewanie
            utworz_przypomnienie_podlewanie(roslina)
        except Exception as e:
            logger.error(f"Błąd tworzenia przypomnienia: {e}")

        return JsonResponse({
            'success': True,
            'message': f'Podlano {roslina.nazwa}! 💧',
            'liczba_podlan': liczba_podlan,
            'ml_zaktualizowane': ml_zaktualizowane,
            'ostatnie_podlewanie': roslina.ostatnie_podlewanie.isoformat()
        })

    except Exception as e:
        logger.error(f"Błąd oznaczania podlania: {e}")
        return JsonResponse({
            'error': str(e)
        }, status=500)


# ============================================
# PRZYPOMNIENIA
# ============================================
@login_required
def lista_przypomnie(request):
    """Feed przypomnień"""
    mode = request.GET.get("view", "upcoming")
    now = timezone.localtime(timezone.now())


    base_qs = (
        Przypomnienie.objects
        .filter(uzytkownik=request.user)
        .select_related("roslina")
    )

    counts = {
        "all": base_qs.count(),
        "upcoming": base_qs.filter(status="oczekujace").count(),
        "done": base_qs.filter(status="wykonane").count(),
    }

    if mode == "done":
        przypomnienia = (
            base_qs.filter(status="wykonane")
            .order_by("-data_wykonania")[:200]
        )
    else:
        przypomnienia = (
            base_qs.filter(status="oczekujace")
            .order_by("data_przypomnienia")[:200]
        )

    return render(
        request,
        "bloomly/lista_przypomnie.html",
        {
            "przypomnienia": przypomnienia,
            "mode": mode,
            "counts": counts,
            "now": now,
        },
    )


@login_required
def szczegoly_przypomnienia(request, id):
    """Szczegóły przypomnienia"""
    przypomnienie = get_object_or_404(Przypomnienie, id=id, uzytkownik=request.user)
    return render(request, 'bloomly/szczegoly_przypomnienia.html', {'przypomnienie': przypomnienie})


@login_required
def wykonaj_przypomnienie(request, id):
    """Wykonanie przypomnienia z formularzem"""
    przyp = get_object_or_404(Przypomnienie, id=id, uzytkownik=request.user)
    roslina = przyp.roslina

    if request.method == "POST":
        form = WykonajPrzypomnienieForm(request.POST)
        if form.is_valid():
            dt = form.cleaned_data["data"]
            stan = form.cleaned_data.get("stan_gleby") or None
            woda = form.cleaned_data.get("ilosc_wody") or None
            notatki = form.cleaned_data.get("notatki", "")

            # 1) Zapisz czynność podlewania
            cz = CzynoscPielegnacyjna.objects.create(
                roslina=roslina,
                uzytkownik=request.user,
                typ="podlewanie",
                data=dt,
                stan_gleby=stan,
                ilosc_wody=woda,
                notatki=notatki,
                wykonane=True,
            )

            # 2) Zamknij przypomnienie
            przyp.status = "wykonane"
            przyp.data_wykonania = dt
            przyp.wyslane = True
            przyp.save(update_fields=["status", "data_wykonania", "wyslane"])

            # 3) ONE-OPEN - utwórz nowe przypomnienie ZAWSZE synchronicznie
            from .models import utworz_przypomnienie_podlewanie

            nowe_przypomnienie = None
            try:
                nowe_przypomnienie = utworz_przypomnienie_podlewanie(roslina)
                if nowe_przypomnienie:
                    logger.info(
                        f"Utworzono nowe przypomnienie dla {roslina.nazwa} "
                        f"na {nowe_przypomnienie.data_przypomnienia}"
                    )
                else:
                    logger.warning(f"utworz_przypomnienie_podlewanie zwróciło None dla {roslina.nazwa}")
            except Exception as e:
                logger.error(f"Błąd tworzenia przypomnienia dla {roslina.nazwa}: {e}")

            # 4) ML - aktualizacja analizy
            try:
                liczba_podlan = CzynoscPielegnacyjna.objects.filter(
                    roslina=roslina, typ="podlewanie", wykonane=True
                ).count()
                if liczba_podlan >= 5:
                    zaktualizuj_analize_rosliny(roslina)
                    logger.info(f"Zaktualizowano ML dla {roslina.nazwa}")
            except Exception as e:
                logger.error(f"Błąd ML po wykonaniu przypomnienia: {e}")

            # Komunikat sukcesu
            if nowe_przypomnienie:
                messages.success(
                    request,
                    f'Zapisano podlewanie dla "{roslina.nazwa}". '
                    f'Nastepne przypomnienie: {nowe_przypomnienie.data_przypomnienia.strftime("%d.%m.%Y")}'
                )
            else:
                messages.success(
                    request,
                    f'Zapisano podlewanie dla "{roslina.nazwa}".'
                )

            return redirect("szczegoly_rosliny", id=roslina.id)
    else:
        initial_dt = timezone.now().replace(microsecond=0, second=0)
        form = WykonajPrzypomnienieForm(initial={"data": initial_dt})

    return render(request, "bloomly/wykonaj_przypomnienie.html", {
        "przypomnienie": przyp,
        "roslina": roslina,
        "form": form,
    })


@login_required
def odloz_przypomnienie(request, id):
    """Odłóż (przesuń) przypomnienie"""
    przypomnienie = get_object_or_404(Przypomnienie, id=id, uzytkownik=request.user)

    if request.method == 'POST':
        dni = int(request.POST.get('dni', 1))
        przypomnienie.odloz(dni)
        messages.success(request, f'Przypomnienie zostalo odlozone o {dni} dni.')
        return redirect('lista_przypomnie')

    return render(request, 'bloomly/odloz_przypomnienie.html', {'przypomnienie': przypomnienie})


@login_required
def ustawienia_przypomnie(request):
    """Ustawienia przypomnień użytkownika"""
    if request.method == 'POST':
        profil = request.user.profiluzytkownika
        profil.powiadomienia_email = request.POST.get('email') == 'on'
        profil.powiadomienia_sms = request.POST.get('sms') == 'on'
        profil.save()

        messages.success(request, 'Ustawienia przypomnie zostaly zaktualizowane!')
        return redirect('ustawienia_przypomnie')

    return render(request, 'bloomly/ustawienia_przypomnie.html')


# ============================================
# FORUM
# ============================================

@login_required
def forum_home(request):
    """Feed forum: wszystkie posty"""
    kategorie_glowne = Kategoria.objects.filter(
        typ="forum", aktywna=True, rodzic__isnull=True
    ).order_by("nazwa")

    posty = (
        Post.objects.filter(status="published")
        .select_related("autor", "kategoria")
        .annotate(num_comments=Count("komentarz"))
    )

    # Filtr po kategorii głównej
    k = request.GET.get("k")
    if k:
        posty = posty.filter(Q(kategoria__slug=k) | Q(kategoria__rodzic__slug=k))

    # Sortowanie
    sort = request.GET.get("sort", "new")
    if sort == "old":
        posty = posty.order_by("created_at")
    elif sort == "popular":
        if hasattr(Post, "wyswietlenia"):
            posty = posty.order_by("-wyswietlenia", "-num_comments", "-created_at")
        else:
            posty = posty.order_by("-num_comments", "-created_at")
    else:
        posty = posty.order_by("-created_at")

    # Paginacja
    paginator = Paginator(posty, 10)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "bloomly/forum/home.html",
        {
            "kategorie_glowne": kategorie_glowne,
            "page_obj": page_obj,
            "sort": sort,
            "selected_k": k,
        },
    )


@login_required
def forum_kategoria(request, slug):
    """Przekierowanie do feedu z filtrem kategorii"""
    get_object_or_404(Kategoria, slug=slug, typ="forum", aktywna=True)
    url = f"{reverse('forum_home')}?k={slug}"
    return redirect(url)


@login_required
def forum_post(request, slug):
    """Szczegóły posta + komentarze"""
    post = get_object_or_404(Post, slug=slug)

    # Licznik wyświetleń
    session_key = f"seen_post_{post.pk}"
    if not request.session.get(session_key, False):
        Post.objects.filter(pk=post.pk).update(wyswietlenia=F("wyswietlenia") + 1)
        request.session[session_key] = True
        post.refresh_from_db(fields=["wyswietlenia"])

    # Dodanie komentarza
    if request.method == "POST" and request.user.is_authenticated and not getattr(post, "zablokowany", False):
        form = KomentarzForm(request.POST)
        if form.is_valid():
            kom = form.save(commit=False)
            kom.post = post
            kom.autor = request.user
            kom.save()
            messages.success(request, "Komentarz dodany.")
            return redirect("forum_post", slug=post.slug)
        komentarz_form = form
    else:
        komentarz_form = KomentarzForm()

    komentarze = post.komentarz_set.select_related("autor").all()

    return render(
        request,
        "bloomly/forum/post.html",
        {"post": post, "komentarze": komentarze, "komentarz_form": komentarz_form},
    )


def _can_delete_comment(user, komentarz):
    """Uprawnienia do usunięcia komentarza"""
    if not user.is_authenticated:
        return False
    return (
            komentarz.autor_id == user.id
            or getattr(komentarz.post, "autor_id", None) == user.id
            or user.is_staff
            or user.is_superuser
    )


@login_required
@require_POST
def forum_usun_komentarz(request, pk):
    """Usunięcie komentarza"""
    komentarz = get_object_or_404(Komentarz, pk=pk)
    post = komentarz.post

    if not _can_delete_comment(request.user, komentarz):
        messages.error(request, "Brak uprawnień.")
        return redirect("forum_post", slug=post.slug)

    komentarz.delete()
    messages.success(request, "Komentarz usunięty.")
    return redirect("forum_post", slug=post.slug)


@login_required
def forum_dodaj_post(request):
    """Dodawanie nowego posta"""
    if request.method == "POST":
        form = PostForm(request.POST, request.FILES)
        if form.is_valid():
            post = form.save(commit=False)
            post.autor = request.user
            post.status = "published"
            post.save()
            messages.success(request, "Post zostal dodany!")
            return redirect("forum_post", slug=post.slug)
    else:
        form = PostForm()

    return render(request, "bloomly/forum/dodaj_post.html", {"form": form})


@login_required
@require_POST
def forum_usun_post(request, slug):
    """Usunięcie posta"""
    post = get_object_or_404(Post, slug=slug)

    if not (post.autor_id == request.user.id or request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Brak uprawnień.")
        return redirect("forum_post", slug=post.slug)

    if getattr(post, "kategoria", None) and getattr(post.kategoria, "slug", None):
        redirect_url = f"{reverse('forum_home')}?k={post.kategoria.slug}"
    else:
        redirect_url = reverse("forum_home")

    post.delete()
    messages.success(request, "Post usunięty.")
    return redirect(redirect_url)


@login_required
def forum_edytuj_post(request, slug):
    """Edycja posta"""
    post = get_object_or_404(Post, slug=slug, autor=request.user)

    if request.method == "POST":
        form = PostForm(request.POST, request.FILES, instance=post)
        if form.is_valid():
            form.save()
            messages.success(request, "Post zostal zaktualizowany!")
            return redirect("forum_post", slug=post.slug)
    else:
        form = PostForm(instance=post)

    return render(request, "bloomly/forum/edytuj_post.html", {"form": form, "post": post})


# ============================================
# BAZA WIEDZY O ROŚLINACH
# ============================================

@login_required
def baza_roslin_home(request):
    """Strona główna bazy wiedzy"""
    form = WyszukiwarkaRoslinForm(request.GET)
    rosliny = BazaRoslin.objects.all()

    if form.is_valid():
        query = form.cleaned_data.get('query')
        poziom = form.cleaned_data.get('poziom_trudnosci')
        toksyczna = form.cleaned_data.get('toksyczna')
        sortowanie = form.cleaned_data.get('sortowanie', 'nazwa_polska')

        if query:
            rosliny = rosliny.filter(
                Q(nazwa_polska__icontains=query) |
                Q(nazwa_naukowa__icontains=query) |
                Q(opis_krotki__icontains=query) |
                Q(rodzina__icontains=query)
            )

        if poziom:
            rosliny = rosliny.filter(poziom_trudnosci=poziom)

        if toksyczna == 'bezpieczna':
            rosliny = rosliny.filter(toksyczna_dla_ludzi=False, toksyczna_dla_zwierzat=False)
        elif toksyczna == 'toksyczna':
            rosliny = rosliny.filter(Q(toksyczna_dla_ludzi=True) | Q(toksyczna_dla_zwierzat=True))

        if sortowanie:
            rosliny = rosliny.order_by(sortowanie)
        else:
            rosliny = rosliny.order_by('nazwa_polska')
    else:
        rosliny = rosliny.order_by('nazwa_polska')

    context = {
        'form': form,
        'rosliny': rosliny,
        'liczba_wynikow': rosliny.count(),
    }
    return render(request, 'bloomly/baza/home.html', context)


def baza_roslin_szczegoly(request, slug):
    """Szczegóły rośliny z bazy"""
    roslina = get_object_or_404(BazaRoslin, slug=slug)

    # Zwiększ licznik wyświetleń
    roslina.wyswietlenia += 1
    roslina.save(update_fields=['wyswietlenia'])

    # Podobne rośliny
    podobne = BazaRoslin.objects.filter(
        rodzina=roslina.rodzina
    ).exclude(id=roslina.id)[:4]

    context = {
        'roslina': roslina,
        'podobne': podobne,
    }
    return render(request, 'bloomly/baza/szczegoly.html', context)


@login_required
def baza_roslin_dodaj(request):
    """Dodawanie rośliny do bazy wiedzy"""
    if request.method == 'POST':
        form = BazaRoslinForm(request.POST, request.FILES)
        if form.is_valid():
            roslina = form.save(commit=False)
            roslina.autor = request.user
            roslina.save()
            messages.success(request, 'Roslina zostala dodana do bazy wiedzy!')
            return redirect('baza_roslin_szczegoly', slug=roslina.slug)
    else:
        form = BazaRoslinForm()

    return render(request, 'bloomly/baza/dodaj.html', {'form': form})


@login_required
def baza_roslin_edytuj(request, slug):
    """Edycja rośliny w bazie wiedzy"""
    roslina = get_object_or_404(BazaRoslin, slug=slug)

    if roslina.autor != request.user and not request.user.is_staff:
        messages.error(request, 'Nie masz uprawnien do edycji tej rosliny.')
        return redirect('baza_roslin_szczegoly', slug=slug)

    if request.method == 'POST':
        form = BazaRoslinForm(request.POST, request.FILES, instance=roslina)
        if form.is_valid():
            form.save()
            messages.success(request, 'Roslina zostala zaktualizowana!')
            return redirect('baza_roslin_szczegoly', slug=roslina.slug)
    else:
        form = BazaRoslinForm(instance=roslina)

    context = {
        'form': form,
        'roslina': roslina,
    }
    return render(request, 'bloomly/baza/edytuj.html', context)


# ============================================
# ANALIZA ML I DASHBOARD ANALITYCZNY
# ============================================

@login_required
def analiza_ml_rosliny(request, id):
    roslina = get_object_or_404(Roslina, pk=id, wlasciciel=request.user)

    # Pobierz lub utwórz analizę
    analiza, created = AnalizaPielegnacji.objects.get_or_create(
        roslina=roslina,
        defaults={'uzytkownik': request.user}
    )

    # Pobierz historię podlewań
    podlewania = CzynoscPielegnacyjna.objects.filter(
        roslina=roslina,
        typ='podlewanie'
    ).order_by('data')

    # Oblicz interwały między podlewaniami
    interwaly = []
    if podlewania.count() >= 2:
        podlewania_list = list(podlewania.values_list('data', flat=True))
        for i in range(1, len(podlewania_list)):
            dni = (podlewania_list[i] - podlewania_list[i - 1]).days
            if 0 < dni <= 60:  # Filtruj outliery
                interwaly.append(dni)

    # Oblicz statystyki
    # Oblicz statystyki
    wzorce = {}
    if interwaly:
        import statistics
        wzorce['interwaly'] = interwaly
        wzorce['srednia'] = statistics.mean(interwaly)
        wzorce['mediana'] = statistics.median(interwaly)
        wzorce['odchylenie'] = statistics.stdev(interwaly) if len(interwaly) > 1 else 0
    else:
        wzorce['interwaly'] = []

    # Dodaj informacje z analizy ML (jeśli istnieją)
    # Dodaj informacje z analizy ML (jeśli istnieją)
    if analiza.typ_modelu:  # ← POPRAWIONE
        wzorce['typ_modelu'] = analiza.typ_modelu
        wzorce['n_samples'] = analiza.liczba_podlan
        wzorce['cv_mae'] = analiza.cv_mae
        wzorce['mae'] = analiza.mae
        wzorce['rmse'] = analiza.rmse
        wzorce['r2'] = analiza.r2_score

        # Składowe pewności
        wzorce['pewnosc_modelu'] = analiza.pewnosc_model
        wzorce['pewnosc_regularnosci'] = analiza.pewnosc_regularnosc
        wzorce['pewnosc_gleby'] = analiza.pewnosc_biologia
        wzorce['pewnosc_wody'] = analiza.pewnosc_biologia
    # Oblicz pory podlewania
    podlewania_z_godzinami = CzynoscPielegnacyjna.objects.filter(
        roslina=roslina,
        typ='podlewanie'
    ).exclude(data__isnull=True)

    pory = {
        'rano': 0,
        'popoludniu': 0,
        'wieczorem': 0,
        'preferowana_pora': None
    }

    for p in podlewania_z_godzinami:
        godzina = p.data.hour
        if 6 <= godzina < 12:
            pory['rano'] += 1
        elif 12 <= godzina < 18:
            pory['popoludniu'] += 1
        elif 18 <= godzina < 24:
            pory['wieczorem'] += 1

    # Znajdź preferowaną porę
    max_count = max(pory['rano'], pory['popoludniu'], pory['wieczorem'])
    if max_count > 0:
        if pory['rano'] == max_count:
            pory['preferowana_pora'] = 'rano'
        elif pory['popoludniu'] == max_count:
            pory['preferowana_pora'] = 'popoludniu'
        elif pory['wieczorem'] == max_count:
            pory['preferowana_pora'] = 'wieczorem'

    # Obsługa formularza zastosowania rekomendacji
    if request.method == 'POST' and 'zastosuj' in request.POST:
        if analiza.rekomendowana_czestotliwosc:
            roslina.czestotliwosc_podlewania = analiza.rekomendowana_czestotliwosc
            roslina.save()
            messages.success(request,
                             f'Częstotliwość podlewania zaktualizowana na {analiza.rekomendowana_czestotliwosc} dni!')
            return redirect('analiza_ml_rosliny', id=roslina.id)

    context = {
        'roslina': roslina,
        'analiza': analiza,
        'wzorce': wzorce,  # ← Zawiera 'interwaly'!
        'pory': pory,
    }

    return render(request, 'bloomly/analiza_ml.html', context)

@login_required
def dashboard_analityczny(request):
    """Dashboard z analizami dla wszystkich roślin"""
    rosliny = Roslina.objects.filter(wlasciciel=request.user, is_active=True)

    analizy = []
    for roslina in rosliny:
        try:
            analiza = AnalizaPielegnacji.objects.get(roslina=roslina, uzytkownik=request.user)
        except AnalizaPielegnacji.DoesNotExist:
            wynik = zaktualizuj_analize_rosliny(roslina)
            analiza = wynik['analiza']

        analizy.append({
            'roslina': roslina,
            'analiza': analiza,
        })

    # Statystyki ogólne
    total_podlania = CzynoscPielegnacyjna.objects.filter(
        uzytkownik=request.user,
        typ='podlewanie',
        wykonane=True
    ).count()

    context = {
        'analizy': analizy,
        'total_podlania': total_podlania,
        'liczba_roslin': rosliny.count(),
    }
    return render(request, 'bloomly/dashboard_analityczny.html', context)


# ============================================
# KALENDARZ
# ============================================

@login_required
def kalendarz_pielegnacji(request):
    """Kalendarz z przypomnieniami i historią pielęgnacji"""
    return render(request, 'bloomly/kalendarz.html')


def _model_has_field(model, field_name: str) -> bool:
    return field_name in {f.name for f in model._meta.get_fields()}


def _safe_dt(s: Optional[str]) -> Optional[datetime]:
    """ISO -> TZ-aware datetime"""
    if not s:
        return None
    dt = parse_datetime(s)
    if dt is None:
        d = parse_date(s)
        if d:
            dt = datetime.combine(d, time.min)
    if dt and timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


def _get_user_plant_ids(user):
    """Zwróć ID roślin użytkownika"""
    fields = {f.name for f in Roslina._meta.get_fields()}
    filt = {}
    if "wlasciciel" in fields:
        filt["wlasciciel"] = user
    elif "owner" in fields:
        filt["owner"] = user
    elif "user" in fields:
        filt["user"] = user
    else:
        return list(Roslina.objects.values_list("id", flat=True))
    return list(Roslina.objects.filter(**filt).values_list("id", flat=True))


def _first_existing_attr(obj, candidates, default=None):
    for name in candidates:
        if hasattr(obj, name):
            val = getattr(obj, name)
            if val is not None:
                return val
    return default


@login_required
@require_GET
def kalendarz_events_json(request):
    """Zdarzenia dla FullCalendar"""
    user = request.user

    start = _safe_dt(request.GET.get("start"))
    end = _safe_dt(request.GET.get("end"))
    if not start or not end:
        now = timezone.now()
        start = now - timedelta(days=60)
        end = now + timedelta(days=60)

    plant_ids = _get_user_plant_ids(user)

    events = []

    REMINDER_COLORS = {
        "oczekujace": ("#ffcc33", "#ffcc33", "#000000"),
        "wyslane": ("#81c784", "#81c784", "#ffffff"),
        "wykonane": ("#43a047", "#43a047", "#ffffff"),
        "odlozone": ("#7986cb", "#7986cb", "#ffffff"),
    }

    HISTORY_COLORS = {
        "podlewanie": ("#38B0DE", "#38B0DE", "#ffffff"),
        "nawozenie": ("#f48fb1", "#f48fb1", "#ffffff"),
        "przycinanie": ("#ff8a65", "#ff8a65", "#ffffff"),
        "przesadzanie": ("#a1887f", "#a1887f", "#ffffff"),
        "_default": ("#CED4DA", "#CED4DA", "#1F2D3D"),
    }

    # Przypomnienia
    ALLOWED_STATUSES = {"oczekujace", "wyslane", "odlozone"}
    reminder_date_fields = ["data_przypomnienia", "termin", "data", "scheduled_for", "due_at", "due_on"]

    przyp_qs = (
        Przypomnienie.objects
        .select_related("roslina")
        .filter(roslina_id__in=plant_ids, status__in=ALLOWED_STATUSES)
    )

    filtered_przyp = []
    for r in przyp_qs:
        dt = _first_existing_attr(r, reminder_date_fields)
        if not dt:
            continue
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt)
        if start <= dt <= end:
            filtered_przyp.append((r, dt))

    for r, dt in filtered_przyp:
        status = getattr(r, "status", "oczekujace")
        bg, bd, fg = REMINDER_COLORS.get(status, REMINDER_COLORS["oczekujace"])
        title = (
                _first_existing_attr(r, ["tytul"], None)
                or (r.get_typ_display() if hasattr(r, "get_typ_display") else str(
            _first_existing_attr(r, ["typ"], "Przypomnienie")))
        )
        events.append({
            "id": f"rem-{r.pk}",
            "title": f"🔔 {title} • {r.roslina.nazwa}",
            "start": timezone.localtime(dt).isoformat(),
            "allDay": False,
            "url": reverse("szczegoly_rosliny", args=[r.roslina_id]) if hasattr(r, "roslina_id") else None,
            "backgroundColor": bg,
            "borderColor": bd,
            "textColor": fg,
            "extendedProps": {
                "kind": "reminder",
                "status": status,
                "roslina": r.roslina.nazwa,
            },
        })

    # Historia
    history_qs = CzynoscPielegnacyjna.objects.select_related("roslina").filter(
        roslina_id__in=plant_ids, data__range=(start, end))

    for c in history_qs:
        typ = getattr(c, "typ", None) or "_default"
        bg, bd, fg = HISTORY_COLORS.get(typ, HISTORY_COLORS["_default"])
        typ_txt = c.get_typ_display() if hasattr(c, "get_typ_display") else str(typ).capitalize()

        bits = []
        if getattr(c, "ilosc_wody", None):
            bits.append(f"{c.ilosc_wody} ml")
        if getattr(c, "stan_gleby", None):
            bits.append(c.get_stan_gleby_display() if hasattr(c, "get_stan_gleby_display") else str(c.stan_gleby))
        subtitle = f" • {' • '.join(bits)}" if bits else ""

        events.append({
            "id": f"hist-{c.pk}",
            "title": f"🌿 {typ_txt} • {c.roslina.nazwa}{subtitle}",
            "start": timezone.localtime(c.data).isoformat(),
            "allDay": False,
            "url": reverse("szczegoly_rosliny", args=[c.roslina_id]),
            "backgroundColor": bg,
            "borderColor": bd,
            "textColor": fg,
            "extendedProps": {
                "kind": "history",
                "typ": typ,
                "roslina": c.roslina.nazwa,
                "notatki": getattr(c, "notatki", "") or "",
                "ilosc_wody": getattr(c, "ilosc_wody", None),
                "stan_gleby": getattr(c, "stan_gleby", None),
            },
        })

    return JsonResponse(events, safe=False)
