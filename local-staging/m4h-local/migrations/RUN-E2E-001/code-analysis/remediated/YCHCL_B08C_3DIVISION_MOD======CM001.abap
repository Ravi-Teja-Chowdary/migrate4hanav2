METHOD EINGEBEN.
  IF xwert1 < '-999999999' OR xwert1 > '+999999999' OR xwert2 < '-999999999' OR xwert2 > '+999999999'.
    RAISE EXCEPTION TYPE zusatzausnahme.
  ENDIF.
  *
  CALL METHOD super.
  CASE sy-subrc.
    WHEN 1.
      RAISE EXCEPTION TYPE wert_ist_null.
  ENDCASE.
  yfunktion = 'DIVISION_MOD'.
ENDMETHOD.
"EINGEBEN