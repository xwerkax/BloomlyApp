from django.contrib import admin
from .models import (
    ProfilUzytkownika, Roslina, CzynoscPielegnacyjna, Przypomnienie,
    Kategoria, Post, Komentarz, BazaRoslin, AnalizaPielegnacji
)

admin.site.register(ProfilUzytkownika)
admin.site.register(Roslina)
admin.site.register(CzynoscPielegnacyjna)
admin.site.register(Przypomnienie)
admin.site.register(Kategoria)
admin.site.register(Post)
admin.site.register(Komentarz)
admin.site.register(BazaRoslin)

@admin.register(AnalizaPielegnacji)
class AnalizaPielegnacjiAdmin(admin.ModelAdmin):
    list_display = [
        'roslina',
        'uzytkownik',
        'rekomendowana_czestotliwosc',
        'pewnosc_rekomendacji',
        'typ_modelu',
        'liczba_podlan',
        'data_aktualizacji'  
    ]
    list_filter = [
        'uzytkownik',
        'typ_modelu',
        'pewnosc_rekomendacji',
        'data_aktualizacji' 
    ]
    search_fields = [
        'roslina__nazwa',
        'roslina__gatunek',
        'uzytkownik__username'
    ]
    readonly_fields = [
        'data_utworzenia',  
        'data_aktualizacji'  
    ]

    fieldsets = (
        ('Podstawowe', {
            'fields': (
                'roslina',
                'uzytkownik',
            )
        }),
        ('Statystyki', {
            'fields': (
                'srednia_czestotliwosc_dni',
                'odchylenie_standardowe',
                'liczba_podlan',
            )
        }),
        ('Pory podlewania', {
            'fields': (
                'podlewa_rano',
                'podlewa_po_poludniu',
                'podlewa_wieczorem',
            )
        }),
        ('Rekomendacje ML', {
            'fields': (
                'typ_modelu',
                'rekomendowana_czestotliwosc',
                'pewnosc_rekomendacji',
            )
        }),
        ('Metryki ML', {
            'fields': (
                'r2_score',
                'mae',
                'rmse',
                'cv_mae',
            ),
            'classes': ('collapse',),
        }),
        ('Składowe pewności', {
            'fields': (
                'pewnosc_model',
                'pewnosc_regularnosc',
                'pewnosc_biologia',
            ),
            'classes': ('collapse',),
        }),
        ('Metadane', {
            'fields': (
                'data_utworzenia',
                'data_aktualizacji',
            ),
            'classes': ('collapse',),
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('roslina', 'uzytkownik')
