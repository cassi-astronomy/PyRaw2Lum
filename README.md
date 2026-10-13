# PyRaw2Lum

PyRaw2Lum převádí celooblohové DSLR RAW snímky na absolutně kalibrované mapy
jasu oblohy v **mag/arcsec² (MSA)** a **cd/m²**. Navazuje na program
`raw2lum 1.35` Jana Hollana a zachovává jeho kalibraci, barevné stupnice,
RGB poměry a korekci vinětace.

Název **PyRaw2Lum** odlišuje současnou Pythonovou aplikaci od původního
Pascalového programu. Podrobné rozdělení autorství je v souboru
[AUTHORS.md](AUTHORS.md). Projekt je šířen pod licencí **GNU GPL verze 2 nebo
pozdější**, stejně jako původní program; úplné znění je v souboru
[LICENSE](LICENSE).

Zdrojový kód a vydání projektu jsou na GitHubu:
[cassi-astronomy/PyRaw2Lum](https://github.com/cassi-astronomy/PyRaw2Lum).

Současné profily jsou určeny pro:

- Canon EOS 600D + Sigma 4,5 mm F2.8 EX DC Circular Fisheye při f/3,5
  (původní laboratorní kalibrace),
- Canon EOS R6 Mark II + tentýž objektiv při f/3,5 (relativní kalibrace z pěti
  párových expozic proti 600D; RMS shody přibližně 1,3 %, největší odchylka
  přibližně 2,5 %).

R6 má větší pixely, takže stejný fyzický obrazový kruh objektivu zabírá asi
2072 pixelů místo 2888 pixelů u 600D. Profil proto používá vlastní střed,
výřez a Bayerovu masku; snímky obou fotoaparátů se neporovnávají pixel proti
pixelu.

Program neznámou sestavu nebo jinou clonu odmítne. Zabraňuje tak vytvoření
věrohodně vypadajícího, ale fyzikálně nesprávného výsledku.

## Co program umí

- dávkově zpracovat libovolný počet light RAWů,
- přijmout více dark RAWů s různými expozičními časy,
- automaticky přečíst model fotoaparátu, ISO, expozici, clonu a čas z EXIFu,
- ke každému lightu vybrat darky se stejným fotoaparátem a ISO a expozicí
  včetně tolerance ±1,0 s,
- více odpovídajících darků zprůměrovat do master darku,
- normalizovat různé expoziční časy a ISO do stejné absolutní jasové stupnice,
- zadat každému lightu samostatnou volitelnou lokalitu,
- převést čas fotoaparátu ze SEC, SELČ, UTC nebo jiné zóny do UTC,
- vytvořit kruhovou mapu MSA v původní 46barevné NPS stupnici,
- vytvořit kruhovou mapu cd/m² v původní Hollanově logaritmické stupnici,
- vytvořit experimentální mapu relativní modré složky a uložit korigované
  lineární R/G/B indexy pro dlouhodobé porovnání barvy oblohy,
- umístit světové strany kruhové mapy do samostatného černého rámu mimo
  měřený obraz,
- po určení světových stran vytvořit panoramata v obou jednotkách,
- orientovat kruhové mapy severem nahoru,
- zahrnout do panoramatu i úzký kalibrovaný pás pod matematickým horizontem,
- určit jednoduchou orientaci jedním známým světovým směrem,
- určit úplnou orientaci a náklon fotoaparátu ze 2–3 ručně označených hvězd,
- experimentálně změřit atmosférickou extinkci Bouguerovým fitem mnoha
  katalogových hvězd, včetně snímků z trackeru i pevného stativu,
- automaticky zkalibrovat radiální vinětaci R, G a B ze série snímků jedné
  umělé hvězdy a uložit opakovaně použitelný JSON profil,
- uložit přesná numerická pole a podrobný JSON report.

Zpracování funguje offline. Malý katalog jasných hvězd pro ruční orientaci je
součástí programu; pro experimentální extinkci je nutné jednou dodat CSV export
Gaia GSPC.

## Instalace a spuštění

Je vyžadován Python 3.10 nebo novější. Závislosti lze nainstalovat příkazem:

```powershell
python -m pip install -r requirements.txt
```

Na Windows potom stačí dvakrát kliknout na `spustit_pyraw2lum.bat`. Původní
`spustit_raw2lum.bat` zůstává jako kompatibilní zástupce. GUI lze
spustit také přímo:

```powershell
python -m raw2lum
```

## Základní pracovní postup

1. Do seznamu **Light RAW snímky** přetáhněte jeden nebo více RAWů nebo použijte
   tlačítko **Přidat…**.
2. Volitelně vyberte light a tlačítkem **Lokalita…** mu přiřaďte název místa.
3. Do seznamu **Dark RAW snímky** přidejte všechny dostupné darky. Mohou být
   pořízené různými expozičními časy.
4. Vyberte časovou zónu, ve které byly nastavené hodiny fotoaparátu.
5. Volitelně nastavte každému lightu orientaci tlačítkem **Orientace…**.
6. Zvolte výstupní složku a velikost PNG.
7. Stiskněte **Spustit zpracování**.

Lighty i darky lze přetahovat přímo z Průzkumníku Windows. Cesty obsahující
mezery jsou podporované.

## Lighty, darky a expoziční údaje

ISO, délku expozice a clonu není nutné přepisovat ručně. Program je načítá
samostatně z každého RAWu. Fotometrický signál normalizuje faktorem:

```text
ISO × expoziční čas / clona²
```

Snímky pořízené například 30 s a 300 s proto při stejném jasu oblohy vyjdou
ve stejné stupnici MSA a cd/m². Podmínkou je lineární odezva snímače a to, že
snímek není podexponovaný nebo saturovaný.

Pro každý light se automaticky použijí pouze darky, které mají:

- stejný model fotoaparátu,
- stejné ISO,
- expoziční čas lišící se nejvýše o 1,0 s včetně.

Nenajde-li se odpovídající dark, daný light se přeskočí s vysvětlením a dávka
pokračuje dalšími snímky. Všechny vyhovující darky se zprůměrují, což snižuje
náhodný šum.

## Lokalita a čas

Každý light může mít vlastní volitelný název lokality. Zobrazí se v nadpisu
výsledné mapy, ale sám o sobě neurčuje zeměpisné souřadnice.

V poli **Čas uložený v EXIFu** lze zvolit:

- Evropa/Praha s automatickým střídáním SEC a SELČ,
- pevné SEC (UTC+1),
- pevné SELČ (UTC+2),
- UTC,
- jiný pevný posun UTC−12 až UTC+14.

Ve výsledných mapách a reportu je čas vždy uveden v UTC.

## Orientace map

Orientace je volitelná a nastavuje se pro každý light samostatně. Bez orientace
vzniknou obě kruhové mapy v původní poloze, ale panorama se nevytváří.

### Jednoduchá orientace

V náhledu klikněte na bod ležící ve známém směru a zvolte **S**, **V**, **J**
nebo **Z**. Lze použít Polárku, jižní směr, kompasový údaj nebo známý bod na
obzoru. Výška označeného bodu nehraje roli.

Tento režim určí světové strany, ale předpokládá, že objektiv mířil přesně do
zenitu. Neopravuje náklon fotoaparátu.

### Astrometrická orientace ze 2–3 hvězd

Tento režim určí světové strany i úplný náklon fotoaparátu.

1. Zadejte zeměpisnou šířku a délku stanoviště v desetinných stupních.
   Severní a východní souřadnice jsou kladné, jižní a západní záporné.
2. V seznamu vyberte jasnou hvězdu.
3. Přejeďte na její polohu v hlavním náhledu. Vpravo se zobrazí lupa 8×
   vytvořená z původních pixelů bez vyhlazování.
4. Klikněte přímo do lupy na střed hvězdy; vybraný bod se přesune pod pevný
   středový kříž. Po kliknutí jej lze doladit klávesami nebo zobrazenými
   tlačítky šipek, vždy o 0,5 pixelu.
5. Stiskněte **Přidat kliknutou**.
6. Stejným způsobem přidejte druhou a ideálně třetí hvězdu.
7. Stiskněte **Vyřešit hvězdy a uložit**.

Dvě hvězdy matematicky stačí. Třetí hvězda je silně doporučená, protože odhalí
chybnou identifikaci nebo nepřesné kliknutí. Vybírejte hvězdy co nejdále od sebe.
Polárka neleží přímo na severním nebeském pólu. Její azimut se podle času může
od čáry **S** lišit přibližně až o 1,2°; program ji proto na severní čáru
záměrně nepřisazuje.
Program spolu s natočením dopočítá také skutečné radiální projekční měřítko
objektivu. Stejné měřítko potom používá pro kruhovou mapu, zenit i polohu
matematického horizontu v panoramatu. Program odmítne příliš blízkou dvojici,
RMS odchylku větší než 0,75° nebo jednotlivou odchylku větší než 1°.

Orientační hodnocení výsledku:

- RMS do 0,3° – velmi dobré,
- 0,3° až 0,7° – běžně použitelné,
- 0,7° až 0,75° – hraniční výsledek; zkontrolujte označení a souřadnice,
- nad 0,75° RMS nebo 1° u jedné hvězdy – řešení se neuloží.

Vestavěný offline seznam obsahuje pojmenované hvězdy přibližně do 2,1 mag ze
severní i jižní oblohy, například Sirius, Canopus, Arcturus, Vega, Capella,
Rigel, Procyon, Betelgeuse, Altair, Aldebaran, Antares, Spica, Pollux, Deneb,
Acrux, Regulus a Polárku. Souřadnice a magnitudy vycházejí z katalogu
[Bright Star Catalogue V/50](https://cdsarc.cds.unistra.fr/viz-bin/cat/V/50).

Při dlouhých expozicích označujte přibližně střed krátké hvězdné stopy.
Program počítá polohy hvězd pro **střed expozice**, nikoli pro čas jejího
začátku uložený v EXIFu. U 180sekundové expozice tak odpadá systematický posun
poloh až přibližně o 0,375° vůči středu stop u hvězd poblíž nebeského rovníku.

### Výsledná orientace

Při jednoduché orientaci se kruhová mapa pouze otočí bez vytváření mezibarev.
Při hvězdné orientaci se mapa geometricky převzorkuje do skutečného zenitu:

- sever je nahoře,
- východ vpravo,
- jih dole,
- západ vlevo,
- nakloněný horizont se opraví.

Panorama má sever uprostřed a pořadí zleva doprava **J – Z – S – V – J**.
Zenit je nahoře. Bílá čára označuje matematický horizont a pod ní zůstává úzký
pás kalibrovaného obrazu, takže se neodříznou blízké objekty a světla.

## Experimentální barva oblohy z RAW RGB

Při každém běžném zpracování vznikne také
`*_barva_oblohy_B_podil.png`. Jde o nepravobarevnou mapu relativního podílu
modrého kanálu po odečtení darku, expoziční normalizaci, vyvážení kanálů podle
profilu fotoaparátu a korekci vinětace:

```text
B podíl = B / (R + G + B)
```

Mapa používá pevnou škálu od 10 do 50 %, aby bylo možné porovnávat snímky z
různých nocí bez automatického přebarvení každého obrázku. Před vykreslením se
kanály lokálně vyhladí přibližně přes 11 × 11 pixelů mapy, čímž se potlačí
jednotlivé hvězdy a šum. Číselná pole uložená v NPZ zůstávají bez tohoto
vyhlazení.

V titulku jsou pro oblast do 5° od skutečného zenitu uvedeny `B/(R+G+B)`,
`B/G` a `R/G`. JSON report obsahuje stejná čísla v části
`sky_color_experimental`. NPZ navíc obsahuje:

- `relative_r`, `relative_g`, `relative_b` – korigované lineární RAW kanály,
- `blue_fraction` – `B/(R+G+B)`,
- `blue_green_ratio` – `B/G`,
- `red_green_ratio` – `R/G`.

Tyto veličiny nejsou spektrem ani absolutní fotopickou, skotopickou či
melanopickou luminancí. Nejlépe slouží ke sledování změn barvy oblohy v čase.
Pro přímé porovnání různých modelů fotoaparátů musí mít každý model ověřenou
barevnou kalibraci; profil R6m2 je zatím pouze křížově odvozen z dvojic snímků
s Canonem 600D.

## Experimentální měření atmosférické extinkce

Karta **Extinkce – experimentální** odhaduje jeden globální extinkční
koeficient `k` v jednotkách mag/airmass z jednoho celooblohového snímku. Pro
každou vhodnou hvězdu měří tok a robustně fituje Bouguerův vztah:

```text
m_inst − V = ZP + k · X + C · (B−V)
```

`X` je vzdušná hmota, `ZP` nulový bod a `C` volitelný barevný člen. Barevný
člen se použije jen tehdy, má-li dost hvězd současně katalogové B i V. Program
automaticky odmítá saturované hvězdy, malé S/N, katalogové sousedy, duplicitní
detekce a odlehlé body fitu.

### Příprava katalogu Gaia

V archivu Gaia vytvořte CSV export následujícího ADQL dotazu. Rozsah do
`V = 8` je pro první pokusy dostatečný:

```sql
SELECT g.source_id, g.ra, g.dec,
       p.b_jkc_mag, p.v_jkc_mag,
       p.b_jkc_flag, p.v_jkc_flag
FROM gaiadr3.gaia_source AS g
JOIN gaiadr3.synthetic_photometry_gspc AS p
  ON g.source_id = p.source_id
WHERE p.v_jkc_mag BETWEEN 3.0 AND 8.0
  AND p.v_jkc_flag = 1
  AND p.b_jkc_flag = 1
```

Program potřebuje sloupce `ra`, `dec` a `v_jkc_mag`; `source_id`,
`b_jkc_mag` a příznaky kvality jsou doporučené. Jasné hvězdy přibližně pod
3 mag nejsou v Gaia GSPC úplné, proto se tato první verze nesnaží stavět fit
jen na nejjasnějších pojmenovaných hvězdách.

### Postup měření

1. Na kartě **Jas oblohy** přidejte light a odpovídající darky, nastavte
   správnou časovou zónu a light vyřešte přes volbu **Orientace…** ze tří
   hvězd. Jednoduché určení jediného světového směru nestačí.
2. Otevřete kartu **Extinkce – experimentální**, vyberte light a CSV katalog.
3. Zvolte **Tracker**, jsou-li hvězdy bodové, nebo **Pevný stativ**. U pevného
   stativu program každé hvězdě samostatně spočítá délku i směr stopy podle
   deklinace a času expozice; Polárka proto dostane téměř bodovou aperturu a
   hvězdy u rovníku delší.
4. Pro první pokus ponechte minimální výšku 20°, mez `V = 7,5` a aperturu
   2,5 pixelu. Potom spusťte měření.

Jakmile je fit hotový, Bouguerův graf se zobrazí přímo na kartě ještě před
zápisem výsledných souborů. Kliknutím na náhled se otevře v plné velikosti,
takže lze okamžitě zkontrolovat rozptyl bodů, odlehlé hvězdy a rozsah vzdušné
hmoty.

Vzniknou tři diagnostické soubory:

- `*_extinkce.json` – výsledek, nastavení a všechna měření,
- `*_extinkce_hvezdy.csv` – tabulka přijatých i odmítnutých hvězd s důvodem,
- `*_extinkce_bouguer.png` – Bouguerův diagram, fit a odlehlé body.

Jde zatím o výzkumnou funkci, nikoli o laboratorně ověřený výstup. Výsledek
je důvěryhodnější při širokém rozsahu vzdušné hmoty, nízkém RMS fitu a bez
mraků, Mléčné dráhy, světelných zdrojů nebo výrazných gradientů pozadí v
aperturách. Samotná formální chyba sklonu nezahrnuje systematickou chybu
kalibrace DSLR, spektrální odezvy ani nepřesnost flatfieldu.

## Kalibrace vinětace umělou hvězdou

Karta **Kalibrace vinětace** změří prostorovou propustnost objektivu ze série
RAW snímků stejného kompaktního světelného zdroje. Může jít například o malý
bílý čtvereček uprostřed monitoru v temné místnosti. Čtvereček zůstává stále
na stejném místě a fotoaparát se natáčí kolem vstupní pupily objektivu tak, aby
se zdroj zobrazil v různých částech obrazového kruhu.

### Pořízení kalibrační série

- použijte nejméně 10, lépe 15–30 RAW snímků,
- zachovejte stejný fotoaparát, objektiv, clonu a ISO,
- zahrňte polohu blízko středu (`r < 0,18`) i blízko okraje (`r > 0,72`),
- na několika poloměrech použijte více azimutů,
- zdroj nesmí být saturovaný ani v nejjasnější středové poloze,
- průběžně opakujte středovou polohu pro kontrolu stability zdroje,
- pořiďte odpovídající darky; přidávají se na kartě **Jas oblohy**.

Program v každém snímku automaticky vyhledá jediný výrazný zdroj, změří jeho
integrální tok odděleně v Bayerových kanálech R, G a B, odečte místní pozadí a
odmítne saturaci. Pro každý kanál robustně fituje kladný radiální model:

```text
T(r) = exp(a1·r² + a2·r⁴ + a3·r⁶)
```

Propustnost je normalizována na `T(0) = 1`. Výsledkem je JSON profil a kontrolní
PNG graf naměřených bodů a křivek R/G/B. Po úspěšné kalibraci GUI nový JSON
automaticky nastaví do pole **Vlastní vinětace** na první kartě. Při běžném
zpracování se potom každý Bayerův kanál opraví samostatně ještě před jejich
složením do fotopické luminance.

Kalibrátor nyní vyžaduje, aby pro daný fotoaparát už existoval základní profil
PyRaw2Lum s výřezem, středem a poloměrem obrazového kruhu. Pro budoucí Canon 6D
Mark I + 8mm rybí oko bude proto nejprve potřeba z ukázkového RAWu doplnit
základní geometrii sestavy; vlastní vinětaci potom změří tato karta.

## Výstupní soubory

Pro každý light vždy vzniknou:

- `*_jas_oblohy_MSA.png` – kruhová mapa s NPS stupnicí,
- `*_jas_oblohy_cd_m2.png` – kruhová mapa s Hollanovou stupnicí,
- `*_barva_oblohy_B_podil.png` – experimentální mapa relativní modré složky,
- `*_numericka_data.npz` – numerická float32 pole jasu a relativních RGB indexů,
- `*_report.json` – EXIF, profil, darky, zenitová hodnota a kontrolní údaje.

Pokud byla určena orientace, vzniknou navíc:

- `*_panorama_MSA.png`,
- `*_panorama_cd_m2.png`.

Experimentální výstupy extinkce jsou popsány v samostatné části výše.

PNG jsou určena k prohlížení a publikování. NPZ obsahuje původní numerickou
měřicí mřížku 1444 × 1444 bez obrazové normalizace a bez otočení. To zachovává
zdrojovou geometrii a maximální přesnost pro další vědecké zpracování.

JSON report u hvězdné orientace obsahuje také:

- souřadnice stanoviště,
- použitý UTC čas,
- názvy a magnitudy označených hvězd,
- jejich obrazové souřadnice,
- jednotlivé úhlové odchylky a RMS,
- rotační matici kamery vůči osám východ–sever–zenit.

## Barevné stupnice

Mapa MSA používá přesnou 46barevnou stupnici původního programu. Hodnoty jsou
uváděny pouze v mag/arcsec².

Mapa cd/m² používá původní logaritmickou Hollanovu stupnici s pěti odstíny na
dekádu. Horní řada legendy označuje celé mocniny deseti a spodní řada skutečné
hranice barevných dekád. Do této mapy se nepřidávají hodnoty MSA.

## Příkazová řádka

Základní dávkové zpracování lze spustit také bez GUI:

```powershell
python -m raw2lum.cli snimek1.CR2 snimek2.CR2 `
  --dark dark_30s.CR2 dark_180s.CR2 `
  --output vystup `
  --timezone Europe/Prague
```

Volby:

- `--scale 1|2|3` – velikost prezentačních PNG,
- `--location "Jizerka"` – společná lokalita pro zadanou dávku,
- `--timezone Europe/Prague` – zóna času uloženého v EXIFu,
- `--north-angle` – pokročilé ruční zadání obrazového úhlu severu.

Astrometrické označování hvězd je dostupné v GUI.

## Přesnost a omezení

- Absolutní fotometrická kalibrace zatím platí pouze pro uvedenou kombinaci
  Canon 600D, Sigma 4,5 mm a f/3,5.
- Profil Canon 6D nebo jiného objektivu vyžaduje samostatnou laboratorní nebo
  referenční kalibraci a vlastní korekci vinětace.
- Přesvětlené části, velmi slabě exponované oblasti a zakryté části oblohy
  nemohou poskytnout spolehlivou luminanci.
- Astrometrickou přesnost omezuje přesnost kliknutí, správnost UTC a souřadnic,
  délka hvězdných stop a přesnost geometrického profilu objektivu.
- Atmosférická refrakce je ve hvězdném řešení vypnutá; pro orientaci používejte
  přednostně hvězdy výše nad obzorem.
- Extinkční fit zatím nepoužívá prostorově proměnnou oblačnost, aerosolové
  vrstvy ani druhý řád barevné extinkce a nemá být považován za profesionální
  fotometrickou kalibraci bez kontroly Bouguerova grafu a tabulky hvězd.

## Testy

Automatické testy lze spustit příkazem:

```powershell
python -m unittest discover -s tests -v
```

Pro porovnání s dodanými Pascalovými referencemi nastavte navíc proměnnou
`RAW2LUM_REFERENCE_DIR` na složku obsahující RAWy a PPM mapy.
