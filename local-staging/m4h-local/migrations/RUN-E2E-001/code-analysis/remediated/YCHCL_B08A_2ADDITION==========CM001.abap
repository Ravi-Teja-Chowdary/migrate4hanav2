METHOD eingeben.
  CALL METHOD super.
  CASE sy-subrc.
    WHEN 1.
      RAISE EXCEPTION TYPE wert_ist_null.
  ENDCASE.
  yfunktion = 'ADDITION'.
ENDMETHOD.
"EINGEBEN