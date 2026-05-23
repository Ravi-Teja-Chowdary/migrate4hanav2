METHOD methode_inst_publ.
  WRITE /.
  'Methode instance public'.
  CALL METHOD me.
  CALL METHOD methode_stat_priv.
ENDMETHOD.
"AUSGABE