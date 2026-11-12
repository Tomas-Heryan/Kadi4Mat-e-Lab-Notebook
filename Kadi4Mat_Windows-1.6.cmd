@echo off
rem ============================================================================
rem  Kadi4Mat_Windows-1.6.cmd                            verze 1.6, 12. 11. 2026
rem  Vydavatel: CEET, VSB-TUO
rem
rem  Provede postup z navodu "Instalace Kadi Lab Manager (CEET edition) v1.0.1
rem  ve VS Code" (INSTAL-Kadi-Lab-Manager-v1.0.1.md) a potom nasadi demo:
rem
rem    KROK 1  Kontrola predpokladu ............... krok 1 navodu
rem    KROK 2  Stazeni vydani v1.0.1 .............. krok 2 navodu
rem    KROK 3  Virtualni prostredi a instalace .... krok 3 navodu
rem    KROK 4  Overeni instalace .................. krok 4 navodu
rem    KROK 5  Token a test pripojeni ............. krok 5 navodu
rem    KROK 6  Nasazeni dema: plan a apply ........ oddil Co dal
rem    KROK 7  Rozsireni a projekt ve VS Code ..... krok 6 navodu, volitelne
rem
rem  Pouziti:
rem    a) spust soubor dvojklikem odkudkoli: projekt se stahne do slozky
rem       Projects v uzivatelskem profilu, nebo se pouzije kopie, ktera tam uz je,
rem    b) nebo jej spust z kopie projektu, ve ktere lezi - z jejiho korene nebo
rem       z podslozky az do treti urovne; pouzije se tato kopie tak, jak je,
rem    c) nebo mu predej cestu ke slozce projektu jako parametr.
rem
rem  Pri kazdem nasazeni v kroku 6 dostanou vsechny identifikatory na konec
rem  casovou stopu ve tvaru RRRRMMDDHHMM, napriklad 202611120824.
rem  Zadani tokenu v kroku 5 je prevzato z prvni verze tohoto skriptu.
rem  Skript nespousti cleanup ani apply --update.
rem  Texty jsou bez diakritiky, aby se zobrazily spravne v kazde konzoli.
rem ============================================================================
setlocal EnableExtensions DisableDelayedExpansion

rem ------------------------------ NASTAVENI ----------------------------------
rem  Vydani projektu a adresa repozitare:
set "VYDANI=v1.0.1"
set "REPOZITAR=https://github.com/Tomas-Heryan/Kadi4Mat-e-Lab-Notebook.git"
rem  Kam se projekt stahne. Slozku lze zmenit; nehodi se slozky synchronizovane
rem  pres OneDrive, protoze virtualni prostredi obsahuje tisice malych souboru:
set "SLOZKA_PROJEKTU=%USERPROFILE%\Projects\Kadi4Mat-e-Lab-Notebook"
rem  Verze Pythonu v poradi, v jakem se zkouseji. Navod pouziva 3.14. Python 3.15
rem  pouzit nelze, protoze zavislost kadi-apy 0.51 vyzaduje verzi nizsi:
set "PY_VERZE_SEZNAM=3.14 3.13 3.12 3.11 3.10"
rem  Balicky pro winget, kdyz Git nebo Python chybi:
set "WINGET_GIT=Git.Git"
set "WINGET_PYTHON=Python.Python.3.14"
rem  Adresa serveru Kadi4Mat. Do .env se doplni jen tehdy, kdyz tam KADI_URL chybi:
set "VYCHOZI_SERVER=https://kadi-test.vsb.cz"
rem  Modely overovane v kroku 4; druhy z nich se v kroku 6 nasazuje na server:
set "MODEL_CEET=model\ceet.yaml"
set "MODEL=model\demo.yaml"
rem  Casova stopa. Pri kazdem nasazeni se z modelu vyse vytvori kopie, v niz se
rem  pripona identifikatoru nahradi aktualnim datem a casem ve tvaru RRRRMMDDHHMM,
rem  napriklad 202611120824. U dema tak stopa nahrazuje priponu -demo.
rem  Identifikator v Kadi4Mat smi mit nejvyse 50 znaku a nejdelsi identifikatory
rem  dema jich maji 38, takze se stopa pripojuje primo, bez oddelovace. Pokud
rem  identifikatory v modelu zkratis, muzes sem oddelovac doplnit, napriklad
rem  pomlcku; povolena jsou mala pismena, cislice, pomlcka a podtrzitko:
set "PREDPONA_STOPY="
rem  Dva kratke prikazy pro Python z .venv, pouzite v kroku 6:
rem    PY_STOPA  vypise aktualni mistni datum a cas jako dvanact cislic
rem    PY_MODEL  nacte model, nastavi v nem priponu identifikatoru a ulozi jej
rem              pod novym nazvem do stejne slozky
set "PY_STOPA=import time;t=time.localtime();print(t.tm_year*10**8+t.tm_mon*10**6+t.tm_mday*10**4+t.tm_hour*100+t.tm_min)"
set "PY_MODEL=import sys,pathlib,yaml;m=yaml.safe_load(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8-sig'));s=m.setdefault('settings',{});s['namespace']=sys.argv[3];pathlib.Path(sys.argv[2]).write_text(yaml.safe_dump(m,allow_unicode=True,sort_keys=False),encoding='utf-8')"
rem  Vydavatel uvadeny v zahlavi vypisu a v napovede. Pouzivej jen pismena bez
rem  diakritiky, cislice, mezery, carky a pomlcky. Bezpecnostni upozorneni Windows
rem  tento udaj neprebira: pole Vydavatel tam vychazi jen z digitalniho podpisu
rem  a soubor .cmd digitalni podpis nest nemuze.
set "VYDAVATEL=CEET, VSB-TUO"
rem ---------------------------------------------------------------------------

set "RC=0"
set "JE_PUSHD="
set "DEMO_NASAZENO="
set "STOPA="
set "K4M_SKRIPT=%~f0"
title Kadi Lab Manager - instalace a nasazeni dema

if "%~1"=="/?" goto Napoveda
if /i "%~1"=="/h" goto Napoveda
if /i "%~1"=="--help" goto Napoveda

echo.
echo ==============================================================================
echo   KADI LAB MANAGER %VYDANI% - instalace a nasazeni dema ve Windows
echo   Vydavatel: %VYDAVATEL%
echo ==============================================================================

rem --- Slozka projektu: 1. parametr, 2. kopie projektu, ve ktere tento soubor
rem     lezi - jeho slozka nebo az tri urovne nad ni, 3. slozka z nastaveni ----
set "PROJEKT=%~1"
if not defined PROJEKT for %%I in ("%~dp0." "%~dp0.." "%~dp0..\.." "%~dp0..\..\..") do if not defined PROJEKT if exist "%%~fI\src\kadi_lab_manager\cli.py" set "PROJEKT=%%~fI"
if not defined PROJEKT set "PROJEKT=%SLOZKA_PROJEKTU%"
for %%I in ("%PROJEKT%\.") do set "PROJEKT=%%~fI"
rem  Lezi-li tento soubor uvnitr slozky projektu, nesmi se pracovni kopie prepinat
rem  na jine vydani: prepnuti by mohlo tento soubor za behu odstranit.
set "SKRIPT_V_PROJEKTU="
for %%I in ("%~dp0." "%~dp0.." "%~dp0..\.." "%~dp0..\..\..") do if /i "%%~fI"=="%PROJEKT%" set "SKRIPT_V_PROJEKTU=1"
echo   Slozka projektu: "%PROJEKT%"


rem ============================================================================
rem  KROK 1 - KONTROLA PREDPOKLADU (krok 1 navodu)
rem ============================================================================
echo.
echo [KROK 1/7] Kontrola predpokladu - krok 1 navodu
echo.
call :NajdiGit
if defined GIT_VERZE echo   Git ......... %GIT_VERZE%
if not defined GIT_VERZE echo   Git ......... nenalezen
echo   Hledam Python verze 3.10 az 3.14 - muze to chvili trvat...
call :HledejPython
if defined PY_PRIKAZ echo   Python ...... %PY_NALEZEN%, prikaz: %PY_PRIKAZ%
if not defined PY_PRIKAZ echo   Python ...... ve verzi 3.10 az 3.14 nenalezen
set "CODE_VERZE="
for /f "delims=" %%A in ('code --version 2^>nul') do if not defined CODE_VERZE set "CODE_VERZE=%%A"
if defined CODE_VERZE echo   VS Code ..... %CODE_VERZE%
if not defined CODE_VERZE echo   VS Code ..... prikaz code nenalezen, krok 7 se vynecha
echo.
echo   Co chybi, nabidne skript doinstalovat az ve chvili, kdy to bude potreba.


rem ============================================================================
rem  KROK 2 - STAZENI VYDANI (krok 2 navodu)
rem ============================================================================
echo.
echo [KROK 2/7] Stazeni vydani %VYDANI% - krok 2 navodu
echo.
if not exist "%PROJEKT%\pyproject.toml" goto K2_Klonuj
echo   Projekt uz ve slozce je - nestahuji jej znovu.
goto K2_Vstup

:K2_Klonuj
call :ZajistiGit
if errorlevel 1 goto Konec
set "RODIC="
for %%I in ("%PROJEKT%\..") do set "RODIC=%%~fI"
if not exist "%RODIC%\" mkdir "%RODIC%"
if not exist "%RODIC%\" goto ChybaSlozka
echo   ^> git clone -c core.autocrlf=false --branch %VYDANI% %REPOZITAR%
echo.
git clone -c core.autocrlf=false --branch %VYDANI% "%REPOZITAR%" "%PROJEKT%"
set "KOD=%errorlevel%"
if not "%KOD%"=="0" goto ChybaKlon
if not exist "%PROJEKT%\pyproject.toml" goto ChybaKlon
echo.
echo   Hlaseni Gitu o stavu "detached HEAD" je v poradku: pracovni kopie je
echo   pripnuta presne na vydani %VYDANI%.

:K2_Vstup
rem  Prikaz ver jen nuluje errorlevel, aby nasledujici test platil pro pushd.
ver >nul
pushd "%PROJEKT%"
if errorlevel 1 goto ChybaSlozka
set "JE_PUSHD=1"
rem  Overeni vydani jako v navodu: git describe --tags
if not exist ".git\" goto K2_BezGitu
if not defined GIT_VERZE goto K2_BezGitu
set "POPIS="
for /f "delims=" %%G in ('git describe --tags 2^>nul') do set "POPIS=%%G"
if "%POPIS%"=="%VYDANI%" goto K2_VydaniOK
echo   Pracovni kopie neni presne na vydani %VYDANI%; git describe hlasi "%POPIS%".
if defined SKRIPT_V_PROJEKTU goto K2_Ponechat
call :Dotaz "  Prepnout ji prikazy git fetch --tags a git checkout %VYDANI%?"
if errorlevel 1 goto K2_Struktura
echo   ^> git fetch --tags
git fetch --tags
echo   ^> git checkout %VYDANI%
git checkout %VYDANI%
set "KOD=%errorlevel%"
if not "%KOD%"=="0" goto ChybaPrepnuti
:K2_VydaniOK
echo   Vydani %VYDANI% overeno prikazem git describe --tags.
goto K2_Struktura
:K2_Ponechat
echo   Tento soubor lezi uvnitr pracovni kopie, proto ji neprepinam a pouziji ji
echo   tak, jak je.
goto K2_Struktura
:K2_BezGitu
echo   Pozn.: slozka neni klon Gitu nebo Git chybi - vydani nelze overit.
:K2_Struktura
set "CHYBI="
call :Zkontroluj "pyproject.toml"
call :Zkontroluj "src\kadi_lab_manager\cli.py"
call :Zkontroluj "%MODEL_CEET%"
call :Zkontroluj "%MODEL%"
call :Zkontroluj "tests\mock_kadi.py"
call :Zkontroluj ".env.example"
if defined CHYBI goto ChybaStruktura


rem ============================================================================
rem  KROK 3 - VIRTUALNI PROSTREDI A INSTALACE (krok 3 navodu)
rem  Programy z .venv se volaji primo, proto neni potreba aktivacni skript
rem  ani zmena ExecutionPolicy - viz tabulka Reseni potizi v navodu.
rem ============================================================================
echo.
echo [KROK 3/7] Virtualni prostredi a instalace - krok 3 navodu
echo.
set "NOVA_INSTALACE="
if not exist ".venv\" goto K3_VytvorVenv
if not exist ".venv\Scripts\python.exe" goto K3_VenvNeuplna
call :VerzePythonu .venv\Scripts\python.exe
if not defined PYVER goto K3_VenvNeuplna
set "VENV_OK="
for %%V in (%PY_VERZE_SEZNAM%) do if "%%V"=="%PYMM%" set "VENV_OK=1"
if defined VENV_OK goto K3_VenvOK
echo   Existujici .venv pouziva Python %PYVER%; nastroj potrebuje verzi 3.10 az 3.14.
goto K3_SmazVenv
:K3_VenvNeuplna
echo   Existujici slozka .venv je neuplna nebo poskozena.
:K3_SmazVenv
echo   Zavri programy, ktere ji pouzivaji, napriklad VS Code.
call :Dotaz "  Smazat slozku .venv a vytvorit ji znovu?"
if errorlevel 1 goto ChybaVenvStara
rmdir /s /q ".venv"
if exist ".venv\" goto ChybaSmazani

:K3_VytvorVenv
call :ZajistiPython
if errorlevel 1 goto Konec
echo   ^> %PY_PRIKAZ% -m venv .venv
%PY_PRIKAZ% -m venv .venv
set "KOD=%errorlevel%"
if not "%KOD%"=="0" goto ChybaNovaVenv
call :VerzePythonu .venv\Scripts\python.exe
if not defined PYVER goto ChybaNovaVenv
echo   Vytvorena nova .venv - Python %PYVER%
goto K3_Pip

:K3_VenvOK
echo   Pouzivam existujici .venv - Python %PYVER%
if not exist ".venv\Scripts\kadi-lab-manager.exe" goto K3_Pip
.venv\Scripts\kadi-lab-manager.exe --version >nul 2>nul
if errorlevel 1 goto K3_Pip
echo   Program je jiz nainstalovan - instalaci neopakuji.
goto K3_Env

:K3_Pip
set "NOVA_INSTALACE=1"
echo.
echo   ^> .venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install --upgrade pip
set "KOD=%errorlevel%"
if not "%KOD%"=="0" echo   Upozorneni: aktualizace pip se nezdarila, kod %KOD%. Pokracuji instalaci.
echo   ^> .venv\Scripts\python.exe -m pip install -e .
.venv\Scripts\python.exe -m pip install -e .
set "KOD=%errorlevel%"
if not "%KOD%"=="0" goto ChybaPip

:K3_Env
if exist ".env" goto Krok4
copy /y ".env.example" ".env" >nul
if not exist ".env" goto ChybaEnv
echo   Vytvoren soubor .env podle .env.example.


rem ============================================================================
rem  KROK 4 - OVERENI INSTALACE (krok 4 navodu)
rem ============================================================================
:Krok4
echo.
echo [KROK 4/7] Overeni instalace - krok 4 navodu
echo.
echo   ^> .venv\Scripts\kadi-lab-manager.exe --version
.venv\Scripts\kadi-lab-manager.exe --version
set "KOD=%errorlevel%"
if not "%KOD%"=="0" goto ChybaProgram
echo.
echo   ^> .venv\Scripts\kadi-lab-manager.exe validate %MODEL_CEET%
.venv\Scripts\kadi-lab-manager.exe validate "%MODEL_CEET%"
set "KOD=%errorlevel%"
if not "%KOD%"=="0" goto ChybaValidate
echo.
echo   ^> .venv\Scripts\kadi-lab-manager.exe validate %MODEL%
.venv\Scripts\kadi-lab-manager.exe validate "%MODEL%"
set "KOD=%errorlevel%"
if not "%KOD%"=="0" goto ChybaValidate
echo.
if not defined NOVA_INSTALACE goto K4_BezTestu
echo   ^> .venv\Scripts\python.exe -m unittest discover -s tests
echo   Testy bezi proti vestavenemu testovacimu serveru a trvaji asi 20 sekund.
.venv\Scripts\python.exe -m unittest discover -s tests
set "KOD=%errorlevel%"
if "%KOD%"=="0" goto Krok5
echo.
echo   [CHYBA] Testy neprosly, kod %KOD%. Ocekavany konec vypisu: Ran 7 tests a OK.
call :Dotaz "  Pokracovat i presto?"
if not errorlevel 1 goto Krok5
set "RC=4"
goto Konec
:K4_BezTestu
echo   Testy z navodu se spousteji jen po nove instalaci. Rucne je spustis takto:
echo       .venv\Scripts\python.exe -m unittest discover -s tests


rem ============================================================================
rem  KROK 5 - TOKEN A TEST PRIPOJENI (krok 5 navodu)
rem ============================================================================
:Krok5
echo.
echo [KROK 5/7] Token a test pripojeni - krok 5 navodu
echo.
rem  Jiz nastavene promenne prostredi maji pred .env prednost.
rem  Ostatni promenne KADI_* se zamerne ponechavaji.
call :IgnorujPromennou KADI_URL
call :IgnorujPromennou KADI_TOKEN
call :IgnorujPromennou KADI_ENV_FILE
rem  Skryte zadani tokenu a zapis do .env obstara PowerShell; jeho kod je na
rem  konci tohoto souboru. Nespousti se zadny soubor .ps1, takze neni treba
rem  menit ExecutionPolicy.
set "K4M_SERVER=%VYCHOZI_SERVER%"
powershell -NoProfile -Command "$k=[IO.File]::ReadAllText($env:K4M_SKRIPT); $i=$k.LastIndexOf('#PS_BLOK_TOKEN',[StringComparison]::Ordinal); if($i -lt 0){exit 98}; & ([ScriptBlock]::Create($k.Substring($i)))"
set "KOD=%errorlevel%"
if "%KOD%"=="0" goto K5_Doctor
if "%KOD%"=="10" goto K5_Doctor
if "%KOD%"=="20" goto ChybaBezTokenu
rem  Nahradni postup presne podle navodu: rucni uprava souboru .env.
echo.
echo   Skryte zadani tokenu se nepodarilo spustit, kod %KOD%. Pouziji postup z navodu:
echo   otevru .env v Poznamkovem bloku. Na radku KADI_TOKEN=TOKEN nahrad slovo TOKEN
echo   svym tokenem, soubor uloz klavesami Ctrl+S a Poznamkovy blok zavri.
notepad ".env"
echo   Az bude soubor .env ulozen, stiskni libovolnou klavesu...
pause >nul

:K5_Doctor
echo.
echo   ^> .venv\Scripts\kadi-lab-manager.exe doctor
echo.
.venv\Scripts\kadi-lab-manager.exe doctor
set "KOD=%errorlevel%"
if "%KOD%"=="0" goto K5_Opravneni
echo.
echo   [CHYBA] Prikaz doctor skoncil s kodem %KOD%. Nejcastejsi priciny:
echo     - HTTP 401: token je neplatny, propadly nebo vydany pro jiny server,
echo       pripadne mu chybi opravneni, ktera server vypise v polozce scopes
echo     - HTTP 403: tvuj ucet nema na serveru k danemu objektu pristup
echo     - TLS: interni certifikacni autorita - do .env dopln KADI_CA_BUNDLE
echo     - network error: server neni z tohoto pocitace dostupny
echo.
call :Dotaz "  Zadat KADI_TOKEN znovu a kontrolu zopakovat?"
if not errorlevel 1 goto Krok5
set "RC=%KOD%"
goto Krok7

:K5_Opravneni
rem  Prikaz doctor skonci kodem 0 a slovem OK i tehdy, kdyz token nesmi cist
rem  zaznamy. Proto se spusti jeste jednou potichu a v jeho vypisu se hleda
rem  hlaseni "records: not readable".
set "NECTE="
for /f "delims=" %%L in ('.venv\Scripts\kadi-lab-manager.exe doctor 2^>^&1 ^| findstr /c:"not readable"') do set "NECTE=1"
if defined NECTE goto ChybaOpravneni
echo.
echo   Ocekavany vysledek podle navodu: v radku "token user" je tve jmeno a vypis
echo   konci radkem OK.


rem ============================================================================
rem  KROK 6 - NASAZENI DEMA NA SERVER (oddil Co dal v navodu)
rem ============================================================================
echo.
echo [KROK 6/7] Nasazeni dema na server - oddil Co dal v navodu
echo.
if defined STOPA goto K6_Plan
rem  Casova stopa a model pro toto nasazeni vznikaji jen jednou za beh skriptu,
rem  i kdyz se kroky 5 a 6 opakuji s novym tokenem.
for /f "delims=" %%S in ('.venv\Scripts\python.exe -c "%PY_STOPA%"') do set "STOPA=%%S"
if not defined STOPA goto ChybaStopa
if "%STOPA:~11,1%"=="" goto ChybaStopa
if not "%STOPA:~12,1%"=="" goto ChybaStopa
for %%I in ("%MODEL%") do set "MODEL_STOPA=%%~dpI%%~nI-%STOPA%%%~xI"
.venv\Scripts\python.exe -c "%PY_MODEL%" "%MODEL%" "%MODEL_STOPA%" "%PREDPONA_STOPY%%STOPA%"
set "KOD=%errorlevel%"
if not "%KOD%"=="0" goto ChybaStopa
if not exist "%MODEL_STOPA%" goto ChybaStopa
echo   Casova stopa tohoto nasazeni: %STOPA%
echo   Vsechny identifikatory budou koncit %PREDPONA_STOPY%%STOPA%, napriklad
echo   proj-project%PREDPONA_STOPY%%STOPA%. Model s touto priponou je ulozen zde:
echo       "%MODEL_STOPA%"
rem  Kontrola modelu s casovou stopou; vypis se zobrazi jen pri chybe.
.venv\Scripts\kadi-lab-manager.exe validate "%MODEL_STOPA%" >nul 2>nul
if not errorlevel 1 goto K6_Plan
echo.
.venv\Scripts\kadi-lab-manager.exe validate "%MODEL_STOPA%"
goto ChybaModelStopa
:K6_Plan
echo.
echo   Nejdriv bezpecny nahled: plan jen porovna model se serverem a nic nemeni.
echo   ^> .venv\Scripts\kadi-lab-manager.exe plan - model s casovou stopou %STOPA%
echo.
.venv\Scripts\kadi-lab-manager.exe plan "%MODEL_STOPA%"
set "KOD=%errorlevel%"
if not "%KOD%"=="0" goto ChybaPlan
echo.
echo   Nasleduje zapis na server: vznikne nova sada polozek s casovou stopou
echo   %STOPA%. Program znovu vypise plan a zepta se:
echo       Apply these changes to ...? [y/N]
echo   Je-li plan v poradku, zadej y a Enter. Bez potvrzeni se nic nezmeni.
echo.
echo   ^> .venv\Scripts\kadi-lab-manager.exe apply - model s casovou stopou %STOPA%
echo.
.venv\Scripts\kadi-lab-manager.exe apply "%MODEL_STOPA%"
set "KOD=%errorlevel%"
if "%KOD%"=="0" goto K6_Hotovo
echo.
echo   Prikaz apply skoncil s kodem %KOD%: zmeny nebyly potvrzeny, nebo nektera
echo   operace selhala. Podrobnosti jsou ve vypisu vyse.
echo   Je-li ve vypisu HTTP 401 s polozkou scopes, chybi tokenu vypsana opravneni.
set "RC=%KOD%"
goto Krok7
:K6_Hotovo
set "DEMO_NASAZENO=1"
echo.
echo   Server odpovida modelu. V prohlizeci otevri Collections a vyhledej kolekci
echo   s identifikatorem proj-project%PREDPONA_STOPY%%STOPA%.


rem ============================================================================
rem  KROK 7 - ROZSIRENI A OTEVRENI PROJEKTU VE VS CODE (krok 6 navodu)
rem ============================================================================
:Krok7
echo.
echo [KROK 7/7] Rozsireni a otevreni projektu ve VS Code - krok 6 navodu, volitelne
if not defined CODE_VERZE goto K7_BezCode
call :Dotaz "  Nainstalovat rozsireni Python, Python Debugger a YAML a otevrit projekt?"
if errorlevel 1 goto Zaver
rem  Prikaz code je ve Windows davkovy soubor, proto se vola pres call.
echo   ^> code --install-extension ms-python.python
call code --install-extension ms-python.python
echo   ^> code --install-extension ms-python.debugpy
call code --install-extension ms-python.debugpy
echo   ^> code --install-extension redhat.vscode-yaml
call code --install-extension redhat.vscode-yaml
echo   ^> code .
call code .
echo.
echo   Otevre se nove okno se slozkou projektu. Na dotaz, zda duverujes autorum
echo   souboru, odpovez kladne - jinak VS Code vypne ladeni i ulohy.
goto Zaver
:K7_BezCode
echo   Prikaz code neni k dispozici. Rozsireni nainstaluj ve VS Code v panelu
echo   Extensions a slozku projektu otevri pres File, Open Folder.

:Zaver
echo.
echo ==============================================================================
if defined DEMO_NASAZENO echo   HOTOVO - instalace je dokoncena a demo je na serveru
if not defined DEMO_NASAZENO echo   INSTALACE JE DOKONCENA - demo na server nasazeno nebylo, viz hlaseni vyse
echo ==============================================================================
echo   Projekt: "%CD%"
echo   Pri dalsim spusteni se stazeni ani instalace neopakuji. Kazde nasazeni
echo   ale vytvori na serveru novou sadu polozek s novou casovou stopou.
if not defined DEMO_NASAZENO goto Konec
echo   Sadu z tohoto behu pozdeji odstranis timto prikazem; token k tomu
echo   potrebuje opravneni record.delete, collection.delete a template.delete:
echo       .venv\Scripts\kadi-lab-manager.exe cleanup --namespace=%PREDPONA_STOPY%%STOPA% --apply --yes
echo   Starsi demo s priponou -demo odstrani stejny prikaz s --namespace=-demo.
goto Konec


rem ============================================================================
rem  CHYBOVE STAVY
rem ============================================================================
:ChybaSlozka
echo.
echo   [CHYBA] Do slozky projektu nelze vstoupit nebo ji nelze vytvorit:
echo           "%PROJEKT%"
set "RC=2"
goto Konec

:ChybaKlon
echo.
echo   [CHYBA] Stazeni projektu se nezdarilo, kod %KOD%. Mozne priciny:
echo     - pocitac nema pristup na GitHub
echo     - cilova slozka uz existuje a neni prazdna. Bud ji smaz ci prejmenuj,
echo       nebo tomuto souboru predej jinou slozku jako parametr:
echo           "%PROJEKT%"
set "RC=2"
goto Konec

:ChybaPrepnuti
echo.
echo   [CHYBA] Pracovni kopii se nepodarilo prepnout na vydani %VYDANI%, kod %KOD%.
echo   Precti si hlaseni Gitu vyse; casto vadi neulozene zmeny ve slozce projektu.
set "RC=2"
goto Konec

:ChybaStruktura
echo.
echo   [CHYBA] Ve slozce projektu chybi soubory oznacene slovem CHYBI. Slozka
echo   neobsahuje uplne vydani %VYDANI%; nejjednodussi je stahnout je do nove slozky.
set "RC=2"
goto Konec

:ChybaVenvStara
echo.
echo   Stavajici .venv zustava beze zmeny. Bez prostredi s Pythonem 3.10 az 3.14
echo   nelze pokracovat.
set "RC=3"
goto Konec

:ChybaSmazani
echo.
echo   [CHYBA] Slozku .venv se nepodarilo smazat. Zavri programy, ktere ji
echo   pouzivaji, a spust tento soubor znovu.
set "RC=3"
goto Konec

:ChybaNovaVenv
echo.
echo   [CHYBA] Virtualni prostredi .venv se nepodarilo vytvorit. Precti si
echo   hlaseni vyse.
set "RC=3"
goto Konec

:ChybaPip
echo.
echo   [CHYBA] Instalace skoncila chybou, kod %KOD%. K pripojeni na server
echo   nepokracuji. Caste priciny:
echo     - pocitac nema pristup k internetu nebo k pypi.org, napriklad kvuli proxy
echo     - "No matching distribution found for kadi-apy": prostredi vzniklo
echo       v Pythonu 3.15 nebo novejsim; smaz slozku .venv a spust soubor znovu
set "RC=4"
goto Konec

:ChybaProgram
echo.
echo   [CHYBA] Program .venv\Scripts\kadi-lab-manager.exe nelze spustit, kod %KOD%.
echo   Smaz slozku .venv ve slozce projektu a spust tento soubor znovu.
set "RC=4"
goto Konec

:ChybaValidate
echo.
echo   [CHYBA] Mistni validace modelu neprosla, kod %KOD%. Oprav chyby uvedene vyse.
set "RC=5"
goto Konec

:ChybaEnv
echo.
echo   [CHYBA] Soubor .env se nepodarilo vytvorit z .env.example.
set "RC=6"
goto Konec

:ChybaBezTokenu
echo.
echo   KADI_TOKEN nebyl zadan, k pripojeni na server proto nepokracuji.
echo   Az budes mit token pripraveny, spust tento soubor znovu - instalace
echo   se uz opakovat nebude.
set "RC=6"
goto Krok7

:ChybaOpravneni
echo.
echo   [CHYBA] Token se k serveru prihlasil, ale nesmi cist zaznamy: prikaz doctor
echo   vypsal "records: not readable". Tokenu chybi opravneni, a proto by selhalo
echo   i nasazeni dema.
echo.
echo   Opravneni jsou soucasti tokenu na serveru a vybiraji se pri jeho vytvareni.
echo   Tento skript ani program je k hotovemu tokenu pridat nemohou. Vytvor proto
echo   v prohlizeci novy token - Settings ^> Access tokens - a zaskrtni u nej
echo   vsechna opravneni vypsana pred zadanim tokenu. V aktualnich verzich Kadi4Mat
echo   smi token bez zaskrtnutych opravneni jen zakladni dotazy. Stary token smaz.
echo.
call :Dotaz "  Zadat novy KADI_TOKEN a kontrolu zopakovat?"
if not errorlevel 1 goto Krok5
set "RC=6"
goto Krok7

:ChybaStopa
echo.
echo   [CHYBA] Model s casovou stopou se nepodarilo vytvorit. Na server se nic
echo   nezapsalo. Precti si hlaseni vyse.
set "RC=5"
goto Krok7

:ChybaModelStopa
echo.
echo   [CHYBA] Model s casovou stopou neprosel kontrolou. Na server se nic nezapsalo.
echo   Hlaseni "is longer than 50 characters" znamena, ze se identifikator
echo   s casovou stopou nevejde do limitu Kadi4Mat: zkrat identifikator v modelu,
echo   nebo vyprazdni PREDPONA_STOPY v nastaveni na zacatku tohoto souboru.
set "RC=5"
goto Krok7

:ChybaPlan
echo.
echo   [CHYBA] Prikaz plan skoncil s kodem %KOD%. Na server se nic nezapsalo.
echo   Je-li ve vypisu HTTP 401 s polozkou scopes, chybi tokenu vypsana opravneni:
echo   vytvor novy token se vsemi opravnenimi vypsanymi pred zadanim tokenu.
echo   HTTP 403 znamena, ze tvuj ucet nema k danemu objektu na serveru pristup.
echo.
call :Dotaz "  Zadat KADI_TOKEN znovu a kroky 5 a 6 zopakovat?"
if not errorlevel 1 goto Krok5
set "RC=%KOD%"
goto Krok7

:Napoveda
echo.
echo   %~nx0 [slozka_projektu]
echo   Vydavatel: %VYDAVATEL%
echo.
echo   Stahne vydani %VYDANI% projektu Kadi4Mat-e-Lab-Notebook, nainstaluje
echo   kadi-lab-manager do .venv, overi instalaci, vyzada KADI_TOKEN, ulozi jej
echo   do .env, spusti doctor, plan a apply a volitelne otevre projekt ve VS Code.
echo   Identifikatory nasazenych polozek konci casovou stopou RRRRMMDDHHMM.
echo.
echo   Slozka projektu se urci v tomto poradi: parametr, kopie projektu, ve ktere
echo   tento soubor lezi, jinak "%SLOZKA_PROJEKTU%".
exit /b 0

:Konec
if defined JE_PUSHD popd
echo.
if not "%RC%"=="0" echo   Skript skoncil s kodem %RC%.
echo   Stiskni libovolnou klavesu pro zavreni okna...
pause >nul
exit /b %RC%


rem ============================================================================
rem  PODPROGRAMY
rem ============================================================================
:Zkontroluj
rem  Overi, ze soubor ve slozce projektu existuje.
if exist "%~1" goto SouborNalezen
echo     CHYBI  %~1
set "CHYBI=1"
exit /b 0
:SouborNalezen
echo     OK     %~1
exit /b 0

:VerzePythonu
rem  Pouziti: call :VerzePythonu prikaz [argumenty]
rem  Zavola "prikaz --version" a cte jen standardni vystup, takze chybova hlaseni
rem  spoustece py vysledek neovlivni. Vraci PYVER, napriklad 3.12.7, a PYMM,
rem  napriklad 3.12. Pri neuspechu zustanou obe promenne prazdne.
set "PYVER="
set "PYMM="
for /f "tokens=1,2" %%A in ('%* --version 2^>nul') do if /i "%%A"=="Python" set "PYVER=%%B"
if not defined PYVER exit /b 1
for /f "tokens=1-3 delims=." %%A in ("%PYVER%") do if not "%%C"=="" set "PYMM=%%A.%%B"
exit /b 0

:HledejPython
rem  Najde Python 3.10 az 3.14: nejdriv spoustecem py od nejnovejsi verze, potom
rem  prikazem python. Vraci PY_PRIKAZ, napriklad py -3.14, a PY_NALEZEN.
set "PY_PRIKAZ="
set "PY_NALEZEN="
for %%V in (%PY_VERZE_SEZNAM%) do call :ZkusSpoustec %%V
if defined PY_PRIKAZ exit /b 0
call :VerzePythonu python
if not defined PYMM exit /b 0
for %%V in (%PY_VERZE_SEZNAM%) do if "%%V"=="%PYMM%" set "PY_PRIKAZ=python"
if defined PY_PRIKAZ set "PY_NALEZEN=%PYVER%"
exit /b 0

:ZkusSpoustec
rem  Pouziti: call :ZkusSpoustec 3.14
if defined PY_PRIKAZ exit /b 0
call :VerzePythonu py -%~1
if not "%PYMM%"=="%~1" exit /b 0
set "PY_PRIKAZ=py -%~1"
set "PY_NALEZEN=%PYVER%"
exit /b 0

:NajdiGit
rem  Vraci GIT_VERZE, napriklad 2.47.0.windows.1, nebo prazdnou promennou.
set "GIT_VERZE="
for /f "tokens=1-3" %%A in ('git --version 2^>nul') do if /i "%%A"=="git" set "GIT_VERZE=%%C"
exit /b 0

:ZajistiGit
rem  Vraci errorlevel 0, je-li Git k dispozici; jinak nastavi RC a vrati 1.
if defined GIT_VERZE exit /b 0
echo   Git neni nainstalovan a pro stazeni projektu je potreba.
where winget >nul 2>nul
if errorlevel 1 goto ZG_BezWinget
call :Dotaz "  Nainstalovat jej prikazem winget install -e --id %WINGET_GIT%?"
if errorlevel 1 goto ZG_Rucne
echo   ^> winget install -e --id %WINGET_GIT%
winget install -e --id %WINGET_GIT%
rem  Okno, ktere uz bezi, o nove nainstalovanem programu nevi; zkusi se proto
rem  i obvykle umisteni Gitu.
call :NajdiGit
if defined GIT_VERZE exit /b 0
if exist "%ProgramFiles%\Git\cmd\git.exe" set "PATH=%ProgramFiles%\Git\cmd;%PATH%"
call :NajdiGit
if defined GIT_VERZE exit /b 0
echo.
echo   Git se v tomto okne nepodarilo najit. Pokud instalace probehla, zavri
echo   toto okno a spust soubor znovu - nove okno uz o Gitu bude vedet.
set "RC=3"
exit /b 1
:ZG_BezWinget
echo   Nastroj winget neni k dispozici.
:ZG_Rucne
echo.
echo   Nainstaluj Git rucne z https://git-scm.com a spust tento soubor znovu.
echo   Pokud uz kopii projektu mas, predej cestu k ni tomuto souboru jako parametr.
set "RC=3"
exit /b 1

:ZajistiPython
rem  Vraci errorlevel 0, je-li Python 3.10 az 3.14 k dispozici; jinak nastavi RC
rem  a vrati 1.
if defined PY_PRIKAZ exit /b 0
echo   Python 3.10 az 3.14 neni nainstalovan a pro vytvoreni .venv je potreba.
where winget >nul 2>nul
if errorlevel 1 goto ZP_BezWinget
call :Dotaz "  Nainstalovat jej prikazem winget install -e --id %WINGET_PYTHON%?"
if errorlevel 1 goto ZP_Rucne
echo   ^> winget install -e --id %WINGET_PYTHON%
winget install -e --id %WINGET_PYTHON%
rem  Okno, ktere uz bezi, o nove nainstalovanem programu nevi; zkusi se proto
rem  i obvykle umisteni spoustece py.
call :HledejPython
if defined PY_PRIKAZ exit /b 0
if exist "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" set "PATH=%LOCALAPPDATA%\Programs\Python\Launcher;%PATH%"
call :HledejPython
if defined PY_PRIKAZ exit /b 0
echo.
echo   Python se v tomto okne nepodarilo najit. Pokud instalace probehla, zavri
echo   toto okno a spust soubor znovu - nove okno uz o Pythonu bude vedet.
set "RC=3"
exit /b 1
:ZP_BezWinget
echo   Nastroj winget neni k dispozici.
:ZP_Rucne
echo.
echo   Nainstaluj Python 3.14 rucne z https://www.python.org/downloads/ a spust
echo   tento soubor znovu. Python 3.15 pouzit nelze.
set "RC=3"
exit /b 1

:Dotaz
rem  Pouziti: call :Dotaz "text otazky"
rem  Ceka na klavesu A nebo Y = ano, N = ne. Vraci errorlevel 0 = ano, 1 = ne.
choice /c ANY /n /m "%~1 [A/N] "
if errorlevel 4 exit /b 1
if errorlevel 3 exit /b 0
if errorlevel 2 exit /b 1
if errorlevel 1 exit /b 0
exit /b 1

:IgnorujPromennou
rem  Pouziti: call :IgnorujPromennou NAZEV
rem  Zrusi promennou jen pro tento beh skriptu a jeji hodnotu nevypisuje.
if not defined %~1 exit /b 0
echo   Pozn.: promenna prostredi %~1 je nastavena mimo .env. Pro tento beh ji
echo          ignoruji, aby platily hodnoty ze souboru .env.
set "%~1="
exit /b 0

rem  Davkova cast souboru zde konci. Radky nize cmd.exe nikdy neprovadi.
goto :eof

#PS_BLOK_TOKEN
# =============================================================================
#  Od radku se znackou vyse az do konce souboru nasleduje kod pro PowerShell,
#  ktery obsluhuje zadani tokenu v KROKU 5. Davkova cast jej nespousti primo;
#  PowerShell si tento blok nacte ze souboru .cmd sam.
#
#  Blok pracuje v koreni projektu se souborem .env:
#    - KADI_URL doplni jen tehdy, kdyz chybi nebo je prazdna,
#    - KADI_TOKEN precte skrytym vstupem a zapise na radek KADI_TOKEN=...,
#    - ostatni radky ponecha a soubor ulozi v UTF-8 bez BOM.
#  Token se nikde nevypisuje a neprochazi prikazovou radkou ani promennymi CMD.
#
#  Navratove kody: 0 = token zapsan, 10 = ponechan token ulozeny v .env,
#                  20 = token nebyl zadan, 99 = neocekavana chyba.
# =============================================================================
$ErrorActionPreference = 'Stop'
try {
    $soubor = Join-Path (Get-Location).ProviderPath '.env'
    $server = $env:K4M_SERVER
    if (-not $server) { $server = 'https://kadi-test.vsb.cz' }
    $radky = New-Object 'System.Collections.Generic.List[string]'
    $zmena = $false

    if (Test-Path -LiteralPath $soubor -PathType Leaf) {
        # Program cte .env jako UTF-8 a BOM neodstranuje; ReadAllLines BOM rozpozna.
        $bajty = [System.IO.File]::ReadAllBytes($soubor)
        $maBom = $false
        if ($bajty.Length -ge 2) {
            if ($bajty[0] -eq 0xEF -and $bajty[1] -eq 0xBB) { $maBom = $true }
            if ($bajty[0] -eq 0xFF -and $bajty[1] -eq 0xFE) { $maBom = $true }
            if ($bajty[0] -eq 0xFE -and $bajty[1] -eq 0xFF) { $maBom = $true }
        }
        if ($maBom) {
            Write-Host '  Pozn.: soubor .env neni v UTF-8 bez BOM - ulozim jej ve spravnem kodovani.'
            $zmena = $true
        }
        foreach ($r in [System.IO.File]::ReadAllLines($soubor)) { $radky.Add($r) }
    }

    # Najde aktivni radky KLIC=HODNOTA podle stejnych pravidel jako config.py:
    # preskakuje prazdne radky a komentare, snese predponu "export " i uvozovky.
    function Najdi([string]$klic) {
        $nalezy = @()
        for ($i = 0; $i -lt $radky.Count; $i++) {
            $t = $radky[$i].Trim()
            if ($t -eq '' -or $t.StartsWith('#')) { continue }
            $p = $t.IndexOf('=')
            if ($p -lt 0) { continue }
            $k = $t.Substring(0, $p).Trim()
            if ($k.StartsWith('export ')) { $k = $k.Substring(7).Trim() }
            if ($k -cne $klic) { continue }
            $h = $t.Substring($p + 1).Trim()
            if ($h.Length -ge 2 -and $h[0] -eq $h[$h.Length - 1] -and ($h[0] -eq [char]34 -or $h[0] -eq [char]39)) {
                $h = $h.Substring(1, $h.Length - 2)
            }
            $nalezy += [pscustomobject]@{ Radek = $i; Hodnota = $h }
        }
        return ,$nalezy
    }

    # --- KADI_URL ------------------------------------------------------------
    $url = ''
    $nalezyUrl = Najdi 'KADI_URL'
    foreach ($n in $nalezyUrl) { if ($url -eq '' -and $n.Hodnota -ne '') { $url = $n.Hodnota } }
    if ($url -eq '') {
        if ($nalezyUrl.Count -gt 0) { $radky[$nalezyUrl[0].Radek] = 'KADI_URL=' + $server }
        else { $radky.Insert(0, 'KADI_URL=' + $server) }
        $url = $server
        $zmena = $true
    }
    Write-Host ('  Server podle KADI_URL v .env: ' + $url)
    if ($url.TrimEnd('/') -ne $server.TrimEnd('/')) {
        Write-Host ('  POZOR: adresa se lisi od vychozi adresy tohoto postupu, ' + $server + '.')
        Write-Host '         Token musi byt vydan pro server uvedeny v .env.'
    }

    # --- Stavajici token -----------------------------------------------------
    $stary = ''
    $nalezyTok = Najdi 'KADI_TOKEN'
    foreach ($n in $nalezyTok) { if ($stary -eq '' -and $n.Hodnota -ne '') { $stary = $n.Hodnota } }
    $maToken = ($stary -ne '' -and $stary.Trim().ToUpperInvariant() -ne 'TOKEN')

    Write-Host ''
    Write-Host ('  Token vytvoris po prihlaseni na ' + $url)
    Write-Host '  v nabidce uctu: Settings > Access tokens. Pri vytvareni zaskrtni tato'
    Write-Host '  opravneni (scopes) - vyjmenovava je README.md. Bez nich smi token'
    Write-Host '  v aktualnich verzich Kadi4Mat jen zakladni dotazy a nasazeni selze:'
    Write-Host '      record.read      record.create      record.update      record.link'
    Write-Host '      collection.read  collection.create  collection.update  collection.link'
    Write-Host '      template.read    template.create    template.update'
    Write-Host '      group.read       user.read'
    Write-Host '  Pokud model nastavuje sdileni a role, zaskrtni take:'
    Write-Host '      record.permissions  collection.permissions  template.permissions'
    Write-Host ''
    if ($maToken) {
        Write-Host '  V .env uz je token ulozen. Samotny Enter jej ponecha, vlozeny text jej nahradi.'
    }
    Write-Host '  Vstup je skryty: token vloz ze schranky, napriklad pravym tlacitkem mysi'
    Write-Host '  nebo Ctrl+V, a potvrd klavesou Enter.'

    # --- Zadani tokenu -------------------------------------------------------
    $token = $null
    $ponechat = $false
    for ($pokus = 1; $pokus -le 3; $pokus++) {
        $tajny = Read-Host -Prompt '  Zadej KADI_TOKEN' -AsSecureString
        $vstup = (New-Object System.Net.NetworkCredential('', $tajny)).Password
        if ($null -eq $vstup) { $vstup = '' }
        $vstup = $vstup.Trim()
        if ($vstup -match '^KADI_TOKEN\s*=\s*(.*)$') { $vstup = $Matches[1].Trim() }
        if ($vstup -eq '') {
            if ($maToken) { $ponechat = $true; break }
            Write-Host '  Token nebyl zadan.'
            continue
        }
        if ($vstup.ToUpperInvariant() -eq 'TOKEN') {
            Write-Host '  Slovo TOKEN je jen zastupny text - vloz skutecny token.'
            continue
        }
        if ($vstup -match '[^\x21-\x7E]') {
            Write-Host '  Token obsahuje mezeru nebo nepovoleny znak - vloz jej prosim znovu.'
            continue
        }
        $token = $vstup
        break
    }

    # --- Zapis do .env -------------------------------------------------------
    if ($null -ne $token) {
        if ($nalezyTok.Count -gt 0) {
            foreach ($n in $nalezyTok) { $radky[$n.Radek] = 'KADI_TOKEN=' + $token }
        }
        else { $radky.Add('KADI_TOKEN=' + $token) }
        $zmena = $true
    }
    if ($zmena) {
        [System.IO.File]::WriteAllLines($soubor, $radky, (New-Object System.Text.UTF8Encoding($false)))
    }

    if ($null -ne $token) {
        Write-Host ('  Token je ulozen v souboru ' + $soubor + ' (delka ' + $token.Length + ' znaku).')
        if (-not $token.StartsWith('pat_')) {
            Write-Host '  Pozn.: tokeny Kadi4Mat obvykle zacinaji znaky pat_ - platnost overi prikaz doctor.'
        }
        exit 0
    }
    if ($ponechat) {
        Write-Host '  Ponechavam token ulozeny v .env.'
        exit 10
    }
    Write-Host '  Token nebyl zadan ani na treti pokus.'
    exit 20
}
catch {
    Write-Host ('  [CHYBA] ' + $_.Exception.Message)
    exit 99
}
