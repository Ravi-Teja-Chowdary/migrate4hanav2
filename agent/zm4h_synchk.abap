REPORT zm4h_synchk.
* Reports the syntax error (line + word + message) of ZM4H_TR_BUILDER8 to a file.
DATA: lt_src TYPE STANDARD TABLE OF string,
      lv_msg TYPE string,
      lv_lin TYPE i,
      lv_wrd TYPE string,
      lv_li  TYPE c LENGTH 6,
      lv_out TYPE string.
READ REPORT 'ZM4H_TR_BUILDER8' INTO lt_src.
SYNTAX-CHECK FOR lt_src MESSAGE lv_msg LINE lv_lin WORD lv_wrd.
lv_li = lv_lin.
CONCATENATE 'line=' lv_li ' word=' lv_wrd ' msg=' lv_msg INTO lv_out RESPECTING BLANKS.
OPEN DATASET '/usr/sap/trans/tmp/m4h_synchk.txt' FOR OUTPUT IN TEXT MODE ENCODING DEFAULT.
IF sy-subrc = 0.
  TRANSFER lv_out TO '/usr/sap/trans/tmp/m4h_synchk.txt'.
  CLOSE DATASET '/usr/sap/trans/tmp/m4h_synchk.txt'.
ENDIF.
