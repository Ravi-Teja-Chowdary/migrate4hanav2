METHOD ychif_b10a_bestandsbuchung~buchen.
  DATA rechner TYPE REF TO ychcl_b08a_1rechner.
  DATA zergebnis TYPE ychde_ergebnis.
  CASE xfunktion.
    WHEN 'SCRUBBED_STRING'.
      CREATE OBJECT rechner TYPE ychcl_b08a_2addition.
    WHEN 'SCRUBBED_STRING'.
      CREATE OBJECT rechner TYPE ychcl_b08a_2subtraktion.
    WHEN OTHERS.
      RAISE EXCEPTION TYPE funktion_ungueltig.
  ENDCASE.
  CALL METHOD rechner.
  CALL METHOD rechner.
  CALL METHOD rechner.
  xbestand_neu = zergebnis.
ENDMETHOD.