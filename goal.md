# Projekt: Inteligentny konfigurator PC

Zbuduj aplikację internetową do składania komputera PC. Użytkownik wybiera komponenty, a aplikacja analizuje ich kompatybilność, opłacalność i wpływ na cały zestaw.

## Konfigurator

Użytkownik powinien móc zbudować komputer z kategorii takich jak CPU, płyta główna, RAM, GPU, dyski, PSU, chłodzenie, obudowa, ...

Zmiana jednego komponentu powinna automatycznie powodować ponowną analizę całej konfiguracji.

## Kompatybilność

Aplikacja powinna wykrywać zarówno twarde konflikty, jak i potencjalne problemy lub ograniczenia.

Przykłady: socket CPU, chipset, wersja BIOS-u, typ RAM, dostępne sloty, rozmiar GPU, format płyty, wysokość chłodzenia, złącza PSU, dostępne linie PCIe, ...

## Zależności między komponentami

Nie ograniczaj analizy do porównywania dwóch komponentów. Niektóre problemy powinny wynikać z kombinacji kilku części.

Przykład: obudowa może obsługiwać osobno GPU i radiator 360 mm, ale ich jednoczesny montaż może powodować konflikt.

## Poziomy problemów

Rozróżniaj problemy blokujące konfigurację, ostrzeżenia i informacje.

Każdy problem powinien jasno wyjaśniać, dlaczego został wykryty.

## Analiza RAM

Porównuj pamięci nie tylko po pojemności i taktowaniu, ale również po ich faktycznym dopasowaniu do aktualnej platformy.

Uwzględnij np. liczbę modułów, kanały pamięci, profile pamięci, ograniczenia kontrolera, obsadzenie slotów, ...

## Analiza zasilania

Oszacuj zapotrzebowanie całego zestawu na energię i oceń, czy wybrany zasilacz jest odpowiedni.

Uwzględnij moc, zapas, wymagane złącza, charakterystykę CPU/GPU, dodatkowe urządzenia, ...

## Ocena zestawu

Oceń konfigurację pod kątem kompatybilności, balansu, opłacalności i możliwości rozbudowy.

Aplikacja powinna wykrywać również zestawy formalnie kompatybilne, ale nieracjonalne, np. bardzo mocne GPU ze słabym CPU.

## Przeznaczenie komputera

Użytkownik może określić przeznaczenie komputera, np. gaming, programowanie, montaż wideo, rendering, workstation, ...

Ocena poszczególnych komponentów powinna zależeć od wybranego zastosowania.

## Budżet

Użytkownik może ustawić budżet, a aplikacja na bieżąco pokazuje koszt zestawu, pozostały budżet i miejsca, w których można potencjalnie zaoszczędzić.

## Porównywanie komponentów

Pozwól porównywać kilka produktów tej samej kategorii.

Porównanie powinno nie tylko prezentować parametry, ale również wskazywać, który produkt lepiej pasuje do aktualnego zestawu i dlaczego.

## Import wszystkich produktów z x-kom

Aplikacja powinna importować **wszystkie produkty dostępne na x-kom.pl** z kategorii związanych z konfiguracją PC, np. procesory, płyty główne, pamięci RAM, karty graficzne, dyski, zasilacze, chłodzenie, obudowy, ...

Dla każdego produktu pobierz możliwie dużo danych potrzebnych do identyfikacji, filtrowania, porównywania, analizy kompatybilności i prezentacji ceny.

Dane produktowe powinny być możliwe do ponownego zaktualizowania, aby konfigurator nie opierał się wyłącznie na jednorazowym imporcie.

## Inne sklepy

Nie jest wymagane importowanie pełnych katalogów produktów z innych sklepów.

Inne sklepy lub porównywarki mogą być wykorzystywane wyłącznie do wyszukiwania ofert cenowych dla produktów znajdujących się już w konfiguratorze.

## Wyszukiwanie cen

Dla każdego komponentu wyszukaj oferty tego samego produktu w innych sklepach lub porównywarkach cenowych.

Pokaż cenę, sklep, dostępność, koszt dostawy, link do oferty, czas sprawdzenia, ...

## Identyfikacja produktów

Aplikacja musi odróżniać podobne, ale różne warianty produktów.

Przykładowo samo `RTX 5070` nie powinno zostać automatycznie uznane za ten sam produkt co konkretny model określonego producenta.

## Najtańszy zestaw

Podsumowanie powinno pokazywać cenę wybranych produktów oraz najtańsze znalezione oferty dla całej konfiguracji.

Jeżeli to możliwe, uwzględnij również koszty dostawy i fakt, że zakup kilku części w jednym sklepie może być tańszy niż wybór najniższej ceny każdego produktu osobno.

## Historia cen

Jeżeli dostępne są wcześniejsze ceny produktu, pokaż ich historię i podstawowe informacje o zmianach ceny.

## Lista produktów

Przy wyborze komponentu pokaż najważniejsze dane pomagające podjąć decyzję: parametry, cenę, kompatybilność, ostrzeżenia, ocenę dopasowania, ...

Lista powinna reagować na już wybrane części.

## Filtrowanie i wyszukiwanie

Pozwól filtrować produkty według parametrów właściwych dla danej kategorii oraz wyszukiwać je po nazwie.

Filtry powinny umożliwiać między innymi pokazanie tylko produktów kompatybilnych z aktualną konfiguracją.

## Zapis konfiguracji

Użytkownik powinien móc zapisać konfigurację, później do niej wrócić i ponownie sprawdzić ceny oraz kompatybilność.

## Udostępnianie

Pozwól udostępnić gotową konfigurację innym osobom za pomocą linku.

## Warianty zestawu

Użytkownik powinien móc skopiować istniejącą konfigurację, zmienić kilka komponentów i porównać oba warianty.

Porównanie powinno uwzględniać cenę, najważniejsze komponenty, kompatybilność, zapotrzebowanie na energię, opłacalność, ...

## Brakujące lub sprzeczne dane

Dane ze sklepów i innych źródeł mogą być niepełne lub sprzeczne. Aplikacja powinna obsługiwać takie sytuacje bez automatycznego uznawania komponentu za kompatybilny.

## Podsumowanie

Gotowa konfiguracja powinna mieć czytelne podsumowanie zawierające komponenty, ceny, najtańsze oferty, całkowity koszt, status kompatybilności, pobór energii, ostrzeżenia, rekomendacje, ...

## Testowanie

Przetestuj najważniejszą logikę biznesową, szczególnie kompatybilność komponentów, zależności między kilkoma częściami, obliczenia kosztów, brakujące dane i przypadki brzegowe.

## Kryterium ukończenia

Rezultatem ma być działająca aplikacja, a nie statyczna makieta.

Nie sugeruję konkretnego sposobu implementacji, architektury ani technologii. Sam podejmij decyzje potrzebne do zrealizowania wymagań.
