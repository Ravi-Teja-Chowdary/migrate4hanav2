METHOD methode_inst_publ.
  WRITE /.
  'SCRUBBED_STRING'.
  CALL METHOD me.
  CALL METHOD methode_stat_priv.
ENDMETHOD.