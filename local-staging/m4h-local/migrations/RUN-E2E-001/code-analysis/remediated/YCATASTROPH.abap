*&---------------------------------------------------------------------*
*& Report  YCATASTROPH                                                 *
*&---------------------------------------------------------------------*
*&  Shows the steps of program analysis tools                          *
*&---------------------------------------------------------------------*
REPORT KATASTROPHALES_PROGRAMM.
* tables vbap.
DATA TABNAME LIKE RSRD1-OBJNAME.
DATA COUNTER TYPE I.
FORM PRINT.
  WRITE /.
  VBAP-VBELN , VBAP-POSNR , VBAP-MATNR.
ENDFORM.
SELECT *
  FROM (
.
  TABNAME ) INTO VBAP.
  PERFORM PRINT.
ENDSELECT.