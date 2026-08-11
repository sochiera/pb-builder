# Demo

`app.py` jest serwerem HTTP opartym na standardowej bibliotece i właścicielem przykładowego katalogu oraz funkcji `analyze`. `client/index.html`, `client/app.js` i `client/style.css` stanowią klienta bez zależności budowania.

`POST /api/analyze` przyjmuje obiekt z identyfikatorami wybranych części oraz opcjonalnym całkowitym budżetem i zwraca koszt, zapotrzebowanie mocy i listę problemów. Nieprawidłowa struktura JSON otrzymuje 400. Brakujący, nieznany lub niewspierany identyfikator jest problemem blokującym, więc niepełne dane nigdy nie stają się zgodne przez pominięcie.

Rekomendowana moc zawiera 35% zapasu i jest zawsze zaokrąglana w górę do wielokrotności 50 W. Klient numeruje żądania analizy i renderuje tylko najnowszą odpowiedź, dlatego opóźniona odpowiedź nie może zastąpić aktualnego wyniku.

`create_server` publikuje wyłącznie wydzielony katalog `client/`, niezależnie od bieżącego katalogu procesu. Kod serwera, testy i dokumentacja nie są zasobami HTTP. Reguły pozostają testowalne poza HTTP. Katalog jest celowo lokalny: nie udaje kompletnej integracji źródła handlowego.

## Profil weryfikacji

- `make smoke` uruchamia testy reguł i HTTP.
- `make ci` uruchamia smoke oraz sprawdza kompilację Pythona.
- `make hardware` sprawdza kompletny, zgodny zestaw referencyjny.
