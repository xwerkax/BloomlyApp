from django.urls import path, reverse_lazy  # uwaga: bez include
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static

from . import views  # bo widoki są w tej samej aplikacji/pakiecie

urlpatterns = [

    # Podstawowe
    path("", views.strona_glowna, name="home"),
    path("rejestracja/", views.rejestracja, name="rejestracja"),
    path("profil/", views.profil, name="profil"),
    path(
        "profil/haslo/",
        auth_views.PasswordChangeView.as_view(
            template_name="bloomly/zmien_haslo.html",
            success_url=reverse_lazy("profil"),
        ),
        name="zmien_haslo",
    ),

    # Rośliny
    path("rosliny/", views.lista_roslin, name="lista_roslin"),
    path("rosliny/dodaj/", views.dodaj_roslina, name="dodaj_roslina"),
    path("rosliny/<int:id>/", views.szczegoly_rosliny, name="szczegoly_rosliny"),
    path("rosliny/<int:id>/edytuj/", views.edytuj_roslina, name="edytuj_roslina"),
    path("rosliny/<int:id>/usun/", views.usun_roslina, name="usun_roslina"),
    path("rosliny/<int:id>/podlej/", views.podlej_roslina, name="podlej_roslina"),
    path("rosliny/<int:id>/czynnosci/nowa/", views.dodaj_czynnosc, name="dodaj_czynnosc"),


    # Przypomnienia
    path("przypomnienia/", views.lista_przypomnie, name="lista_przypomnie"),
    path("przypomnienia/<int:id>/", views.szczegoly_przypomnienia, name="szczegoly_przypomnienia"),
    path("przypomnienia/<int:id>/wykonaj/", views.wykonaj_przypomnienie, name="wykonaj_przypomnienie"),
    path("przypomnienia/<int:id>/odloz/", views.odloz_przypomnienie, name="odloz_przypomnienie"),
    path("przypomnienia/ustawienia/", views.ustawienia_przypomnie, name="ustawienia_przypomnie"),

    # === Forum ===
    path("forum/", views.forum_home, name="forum_home"),
    path("forum/kategoria/<slug:slug>/", views.forum_kategoria, name="forum_kategoria"),
    path("forum/post/<slug:slug>/", views.forum_post, name="forum_post"),
    path("forum/nowy/", views.forum_dodaj_post, name="forum_dodaj_post"),
    path("forum/post/<slug:slug>/edytuj/", views.forum_edytuj_post, name="forum_edytuj_post"),
    path("forum/komentarz/<int:pk>/usun/", views.forum_usun_komentarz, name="forum_usun_komentarz"),
    path("forum/post/<slug:slug>/usun/", views.forum_usun_post, name="forum_usun_post"),

    # Baza wiedzy
    path("baza/", views.baza_roslin_home, name="baza_roslin_home"),
    path("baza/dodaj/", views.baza_roslin_dodaj, name="baza_roslin_dodaj"),
    path("baza/<slug:slug>/edytuj/", views.baza_roslin_edytuj, name="baza_roslin_edytuj"),
    path("baza/<slug:slug>/", views.baza_roslin_szczegoly, name="baza_roslin_szczegoly"),

    # Analityka ML
    path("analityka/", views.dashboard_analityczny, name="dashboard_analityczny"),
    path("rosliny/<int:id>/analiza/", views.analiza_ml_rosliny, name="analiza_ml_rosliny"),

    # Kalendarz
    path("kalendarz/", views.kalendarz_pielegnacji, name="kalendarz_pielegnacji"),
    path("kalendarz/events.json", views.kalendarz_events_json, name="kalendarz_events_json"),
    path("rosliny/<int:id>/oznacz-podlanie/", views.oznacz_podlanie, name="oznacz_podlanie"),
]

# Serwowanie plików mediów w DEV (avatary itd.)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

