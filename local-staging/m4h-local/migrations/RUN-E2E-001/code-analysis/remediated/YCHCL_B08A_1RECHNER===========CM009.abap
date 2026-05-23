METHOD ychif_b10b_einauszaehlung~zaehlen.
  DATA rechner TYPE REF TO ychcl_b08a_1rechner.
  DATA zergebnis TYPE ychde_ergebnis.
  CASE xfunktion.
    WHEN 'HEREIN'.
      CREATE OBJECT rechner TYPE ychcl_b08a_2addition.
    WHEN 'HINAUS'.
      CREATE OBJECT rechner TYPE ychcl_b08a_2subtraktion.
    WHEN OTHERS.
      RAISE EXCEPTION TYPE funktion_ungueltig.
  ENDCASE.
  CALL METHOD rechner.
  CALL METHOD rechner.
  CALL METHOD rechner.
  xanzahl_neu = zergebnis.
ENDMETHOD.
"YCHIF_B10B_EINAUSZAEHLUNG~ZAEHLEN