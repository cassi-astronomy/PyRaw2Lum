"""Cesko-anglicka lokalizace GUI, hlaseni a obrazovych vystupu."""

from __future__ import annotations

import json
import os
from pathlib import Path


LANGUAGES = {"cs": "Čeština", "en": "English"}
_language = "cs"


EN: dict[str, str] = {
    "PyRaw2Lum – měření jasu oblohy": "PyRaw2Lum – sky brightness measurement",
    "Jas oblohy": "Sky brightness",
    "Kalibrovaná celooblohová fotometrie · Canon 600D / R6m2 + Sigma 4,5 mm": "Calibrated all-sky photometry · Canon 600D / R6m2 + Sigma 4.5 mm",
    "Light RAW snímky": "Light RAW images",
    "Light RAW soubor": "Light RAW file",
    "Lokalita (volitelná)": "Location (optional)",
    "Přetáhněte sem jeden nebo více light RAWů, nebo použijte tlačítko Přidat…": "Drop one or more light RAW files here, or use Add…",
    "Přidat…": "Add…",
    "Lokalita…": "Location…",
    "Orientace…": "Orientation…",
    "Odebrat": "Remove",
    "Vymazat": "Clear",
    "Dark RAW snímky": "Dark RAW images",
    "Přidejte darky pro všechny použité expoziční časy. Program pro každý light vybere shodný fotoaparát a ISO, expozice ±1,0 s.": "Add darks for all exposure times used. For every light, the program selects the same camera and ISO with an exposure tolerance of ±1.0 s.",
    "Výstupní složka": "Output folder",
    "Vlastní vinětace": "Custom vignetting",
    "Vybrat…": "Browse…",
    "Volitelné: JSON vytvořený na kartě Kalibrace vinětace; prázdné = vestavěný profil.": "Optional: JSON created on the Vignetting calibration tab; empty = built-in profile.",
    "Čas uložený v EXIFu": "Time stored in EXIF",
    "Ve výsledném obrázku bude čas vždy přepočten a uveden v UTC.": "The output image always shows time converted to UTC.",
    "Velikost prezentačního PNG:": "Presentation PNG size:",
    "1× (nativní mapa)": "1× (native map)",
    "Spustit zpracování": "Start processing",
    "Extinkce – experimentální": "Extinction – experimental",
    "Atmosférická extinkce": "Atmospheric extinction",
    "Experimentální Bouguerův fit z izolovaných nesaturovaných hvězd Gaia GSPC. Light musí mít nejprve vyřešenou astrometrickou orientaci ze hvězd.": "Experimental Bouguer fit using isolated, unsaturated Gaia GSPC stars. The light image must first have a star-based astrometric orientation solution.",
    "Gaia GSPC CSV": "Gaia GSPC CSV",
    "CSV musí obsahovat source_id, ra, dec, v_jkc_mag a volitelně b_jkc_mag a v_jkc_flag.": "CSV must contain source_id, ra, dec, v_jkc_mag and optionally b_jkc_mag and v_jkc_flag.",
    "Způsob pořízení": "Capture method",
    "Tracker – bodové hvězdy": "Tracker – point-like stars",
    "Pevný stativ – individuální stopy podle deklinace": "Fixed tripod – individual trails by declination",
    "Výběr a fotometrie hvězd": "Star selection and photometry",
    "Minimální výška nad obzorem": "Minimum altitude",
    "Nejslabší katalogová hvězda V": "Faintest catalogue star V",
    "Poloměr apertury": "Aperture radius",
    "px mapy": "map px",
    "Změřit extinkci": "Measure extinction",
    "Po změření se zde ihned zobrazí Bouguerův graf.": "The Bouguer plot appears here immediately after measurement.",
    "Snímky na trackeru používají kruhovou aperturu. U pevného stativu se pro každou hvězdu vypočte vlastní stopa mezi začátkem a koncem expozice. Čas astrometrie i extinkce se vztahuje ke středu expozice.": "Tracker images use a circular aperture. For a fixed tripod, an individual trail from the start to the end of the exposure is calculated for every star. Astrometry and extinction both refer to mid-exposure time.",
    "Kalibrace vinětace": "Vignetting calibration",
    "Kalibrační RAW snímky": "Calibration RAW images",
    "Přidejte nejméně 10 RAWů stejného umělého zdroje v různých částech obrazového kruhu. Doporučeno je 15–30 poloh, včetně středu a okraje. Použijí se odpovídající darky z karty Jas oblohy.": "Add at least 10 RAW images of the same artificial source at different positions in the image circle. 15–30 positions including the centre and edge are recommended. Matching darks from the Sky brightness tab are used.",
    "Zdroj nesmí být saturovaný. Fotoaparát, ISO a clona mají zůstat stejné; expozici lze měnit, ale stabilní expozice je přesnější. Program změří samostatný radiální profil R, G a B.": "The source must not be saturated. Keep camera, ISO and aperture unchanged; exposure may vary, although a fixed exposure is more accurate. Separate radial R, G and B profiles are measured.",
    "Změřit a uložit profil": "Measure and save profile",
    "Po změření se zde zobrazí profil propustnosti R/G/B.": "The R/G/B transmission profile appears here after measurement.",
    "Vyberte snímek": "Select an image",
    "Nejprve vyberte jeden nebo více light snímků.": "First select one or more light images.",
    "Lokalita snímku": "Image location",
    "Zadejte lokalitu pro vybrané snímky (prázdná = bez lokality):": "Enter a location for the selected images (empty = no location):",
    "Vyberte jeden snímek": "Select one image",
    "Pro určení světových stran vyberte právě jeden light snímek.": "Select exactly one light image to determine cardinal directions.",
    "Náhled nelze vytvořit": "Cannot create preview",
    "Klikněte na známý směr, nebo postupně na 2–3 vybrané jasné hvězdy. Astrometrie opraví také náklon fotoaparátu.": "Click a known direction, or successively click 2–3 selected bright stars. Astrometry also corrects camera tilt.",
    "Lupa 8×": "Magnifier 8×",
    "Přejeďte myší nad hlavním náhledem.\nKliknutím do lupy přesuňte hvězdu\npřesně pod středový kříž.\nKlávesy nebo tlačítka: krok 0,5 px": "Move the mouse over the main preview.\nClick inside the magnifier to place the star\nexactly under the central crosshair.\nArrow keys or buttons: 0.5 px step",
    "Jednoduchá orientace jedním směrem": "Simple orientation using one direction",
    "Označený směr:": "Marked direction:",
    "Sever (S)": "North (N)",
    "Východ (V)": "East (E)",
    "Jih (J)": "South (S)",
    "Západ (Z)": "West (W)",
    "Směr není označen": "Direction not marked",
    "Nejprve klikněte na bod ve známém světovém směru.": "First click a point in a known cardinal direction.",
    "Uložit směr": "Save direction",
    "Astrometrická orientace ze 2–3 hvězd": "Astrometric orientation from 2–3 stars",
    "Šířka:": "Latitude:",
    "Délka:": "Longitude:",
    "Střed expozice: ": "Mid-exposure: ",
    "čas v EXIFu chybí": "EXIF time missing",
    "Hvězda:": "Star:",
    "Hvězda není označena": "Star not marked",
    "Nejprve klikněte na vybranou hvězdu v náhledu.": "First click the selected star in the preview.",
    "Přidat kliknutou": "Add clicked star",
    "Chybí čas": "Time missing",
    "RAW neobsahuje použitelný čas pořízení.": "The RAW file has no usable capture time.",
    "Astrometrii nelze vyřešit": "Cannot solve astrometry",
    "Příliš velká odchylka": "Residual too large",
    "Astrometrie uložena": "Astrometry saved",
    "Vyřešit hvězdy a uložit": "Solve stars and save",
    "Bez orientace": "No orientation",
    "Zrušit": "Cancel",
    "Vyberte light RAW snímky": "Select light RAW images",
    "Vyberte dark RAW snímky": "Select dark RAW images",
    "Vyberte kalibrační RAWy umělé hvězdy": "Select artificial-star calibration RAWs",
    "Vyberte výstupní složku": "Select output folder",
    "Vyberte profil vinětace PyRaw2Lum": "Select a PyRaw2Lum vignetting profile",
    "Vyberte export katalogu Gaia GSPC": "Select a Gaia GSPC catalogue export",
    "RAW snímky": "RAW images",
    "Všechny soubory": "All files",
    "CSV soubory": "CSV files",
    "Profil vinětace JSON": "Vignetting profile JSON",
    "Bouguerův diagram – rychlá kontrola": "Bouguer diagram – quick check",
    "Profil vinětace – rychlá kontrola": "Vignetting profile – quick check",
    "Málo snímků": "Too few images",
    "Přidejte alespoň 10 kalibračních RAW snímků.": "Add at least 10 calibration RAW images.",
    "Chybí dark": "Dark missing",
    "Na kartě Jas oblohy přidejte odpovídající dark RAW.": "Add a matching dark RAW on the Sky brightness tab.",
    "Hledám zdroj a měřím jednotlivé polohy…": "Finding the source and measuring individual positions…",
    "Neplatné nastavení": "Invalid settings",
    "Zkontrolujte číselné volby extinkce.": "Check the numerical extinction settings.",
    "Chybí light": "Light missing",
    "Chybí katalog": "Catalogue missing",
    "Přidejte odpovídající dark RAW na první kartě.": "Add a matching dark RAW on the first tab.",
    "Přidejte alespoň jeden light RAW snímek.": "Add at least one light RAW image.",
    "Přidejte alespoň jeden dark RAW snímek.": "Add at least one dark RAW image.",
    "Vyberte light RAW ze seznamu první karty.": "Select a light RAW from the first tab.",
    "Vyberte existující CSV export Gaia GSPC.": "Select an existing Gaia GSPC CSV export.",
    "Chybí astrometrie": "Astrometry missing",
    "Pro tento light nejprve na první kartě vyřešte orientaci ze 2–3 hvězd.": "First solve this light image's orientation from 2–3 stars on the first tab.",
    "Výška nebo mezní V magnituda jsou mimo povolený rozsah.": "Altitude or limiting V magnitude is outside the allowed range.",
    "Poloměr apertury musí být 1 až 8 pixelů.": "Aperture radius must be 1 to 8 pixels.",
    "Počítám fotometrii a Bouguerův fit…": "Computing photometry and Bouguer fit…",
    "Chybí profil": "Profile missing",
    "Vybraný JSON profil vinětace neexistuje.": "The selected JSON vignetting profile does not exist.",
    "Spouštím zpracování…": "Starting processing…",
    "Dokončeno s chybami": "Completed with errors",
    "Hotovo": "Done",
    "Všechny snímky byly úspěšně zpracovány.": "All images were processed successfully.",
    "Fit je hotový – graf je zobrazen, ukládám výstupy…": "Fit complete – the plot is displayed; saving outputs…",
    "Extinkci nelze změřit": "Cannot measure extinction",
    "Fit je hotový – zobrazuji profil a ukládám JSON…": "Fit complete – displaying profile and saving JSON…",
    "Kalibrace vinětace dokončena": "Vignetting calibration complete",
    "Profil byl uložen a vybrán pro další zpracování.": "The profile was saved and selected for further processing.",
    "Vinětaci nelze zkalibrovat": "Cannot calibrate vignetting",
    "jen kruhová mapa": "round map only",
    "směr určen": "direction set",
    "astrometrie": "astrometry",
    "Evropa/Praha – automaticky SEC/SELČ": "Europe/Prague – automatic CET/CEST",
    "SEC – pevně UTC+01:00": "CET – fixed UTC+01:00",
    "SELČ – pevně UTC+02:00": "CEST – fixed UTC+02:00",
    "Jiný pevný posun UTC": "Other fixed UTC offset",
    "Analyzuji ": "Analysing ",
    "Pouzite darky: ": "Darks used: ",
    "Ulozeno ": "Saved ",
    "Hotovo: ": "Done: ",
    "CHYBA": "ERROR",
    "Přeskočené soubory: ": "Skipped files: ",
    "Mapa jasu oblohy": "Sky brightness map",
    "Mapa luminance oblohy": "Sky luminance map",
    "Barevný index oblohy – podíl modrého RAW kanálu": "Sky colour index – blue RAW channel fraction",
    "Zenit": "Zenith",
    "obzor": "horizon",
    "Panorama jasu oblohy": "Sky brightness panorama",
    "Panorama luminance oblohy": "Sky luminance panorama",
    "Orientace panoramatu": "Panorama orientation",
    "Bougueruv diagram atmosfericke extinkce": "Bouguer diagram of atmospheric extinction",
    "Vzduchova hmota X": "Air mass X",
    "modre = pouzite, sede = odmitnute": "blue = used, grey = rejected",
    "Kalibrace vinetace umele hvezdy": "Artificial-star vignetting calibration",
    "R / G / B: relativni propustnost": "R / G / B: relative transmission",
    "Normalizovany polomer obrazoveho kruhu": "Normalised image-circle radius",
    "Propustnost": "Transmission",
    "Experimentální relativní RGB index; nejde o spektrum ani o fotopickou, skotopickou či melanopickou luminanci.": "Experimental relative RGB index; not a spectrum or photopic, scotopic, or melanopic luminance.",
    "VÝSLEDEK (experimentální)": "RESULT (experimental)",
    "Extinkce k:": "Extinction k:",
    "Použité hvězdy:": "Stars used:",
    "změřených": "measured",
    "kandidátů": "candidates",
    "Rozsah vzdušné hmoty:": "Air-mass range:",
    "Barevný člen C:": "Colour term C:",
    "Barevný člen: nebyl fitován": "Colour term: not fitted",
    "Střed expozice:": "Mid-exposure:",
    "CSV hvězd:": "Star CSV:",
    "Bouguerův graf:": "Bouguer plot:",
    "Zpracovávám ": "Processing ",
    "PROFIL ULOŽEN": "PROFILE SAVED",
    "Graf:": "Plot:",
    "RMS fitu:": "Fit RMS:",
    "Profil je automaticky vybraný na kartě Jas oblohy.": "The profile has been selected automatically on the Sky brightness tab.",
    "RMS odchylka je ": "RMS residual is ",
    "a nejhorší hvězda ": "and the worst star is ",
    "Požadováno je nejvýše 0,75° RMS a 1,00° pro jednotlivou hvězdu. Zkontrolujte kliknutí, identifikaci hvězd, čas a souřadnice.": "The maximum allowed values are 0.75° RMS and 1.00° for an individual star. Check the clicks, star identification, time, and coordinates.",
    "Odchylky hvězd:": "Star residuals:",
    "Korekce projekčního měřítka:": "Projection-scale correction:",
}


REPLACEMENTS = (
    ("V souboru ", "File "),
    (" chybi ", " is missing "),
    ("Nebyl zadan zadny dark RAW.", "No dark RAW was provided."),
    ("Pro ", "For "),
    (" nebyl nalezen ", " no matching "),
    ("Nalezene darky nemaji rozmery kompatibilni s light snimkem.", "The matching darks have dimensions incompatible with the light image."),
    ("Nepodporovana Bayerova maska", "Unsupported Bayer pattern"),
    ("musi byt", "must be"),
    ("neni platna", "is invalid"),
    ("Po kontrole odlehlych bodu zustalo prilis malo hvezd.", "Too few stars remain after outlier rejection."),
    ("Katalog", "Catalogue"),
    ("hvezd", "stars"),
    ("snimku", "images"),
    ("Zdroj", "Source"),
    ("saturovany", "saturated"),
)


def _settings_path() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home()))
    return base / "PyRaw2Lum" / "settings.json"


def load_language() -> str:
    try:
        value = json.loads(_settings_path().read_text(encoding="utf-8")).get("language")
        return value if value in LANGUAGES else "cs"
    except (OSError, ValueError, TypeError):
        return "cs"


def save_language(language: str) -> None:
    if language not in LANGUAGES:
        raise ValueError(f"Unsupported language: {language}")
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"language": language}, indent=2), encoding="utf-8")


def set_language(language: str, persist: bool = False) -> None:
    global _language
    if language not in LANGUAGES:
        raise ValueError(f"Unsupported language: {language}")
    _language = language
    if persist:
        save_language(language)


def get_language() -> str:
    return _language


def tr(text: str, language: str | None = None) -> str:
    """Prelozi znamy text; u dynamickych hlaseni pouzije opatrne nahrady frazi."""

    lang = language or _language
    if lang != "en" or not isinstance(text, str):
        return text
    if text in EN:
        return EN[text]
    translated = text
    for source, target in sorted(EN.items(), key=lambda pair: len(pair[0]), reverse=True):
        if source in translated:
            translated = translated.replace(source, target)
    for source, target in REPLACEMENTS:
        if source in translated:
            translated = translated.replace(source, target)
    return translated
