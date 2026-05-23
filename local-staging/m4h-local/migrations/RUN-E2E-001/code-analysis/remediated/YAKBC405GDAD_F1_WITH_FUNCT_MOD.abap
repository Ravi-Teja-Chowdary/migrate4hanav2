*&---------------------------------------------------------------------*
*& Report  YAKBC405GDAD_F1_WITH_FUNCT_MOD                              *
*&                                                                     *
*&---------------------------------------------------------------------*
*&              Help request: F1 help                                  *
*&---------------------------------------------------------------------*
REPORT YAKBC405GDAD_F1_WITH_FUNCT_MOD.
NODES : SPFLI.
SELECT-OPTIONS SO_DEPT FOR SPFLI-DEPTIME.
* Default values for selecetion criteria of the logical database
INITIALIZATION.
CARRID-LOW = 'LH'.
CARRID-SIGN = 'I'.
CARRID-OPTION = 'EQ'.
APPEND CARRID.
CITY_FR = 'FRANKFURT'.
* Check of selection criterion SO_DEPT
AT SELECTION-SCREEN ON SO_DEPT.
IF ( SO_DEPT-LOW GT '220000' OR SO_DEPT-HIGH GT '220000' ) AND CITY_FR EQ 'FRANKFURT'.
  MESSAGE E046 ( BCTRAIN ).
ENDIF.
* Help request for SO_DEPT (F1 help)
AT SELECTION-SCREEN ON HELP-REQUEST FOR SO_DEPT.
CALL FUNCTION 'POPUP_DISPLAY_TEXT'
  EXPORTING
    LANGUAGE = SY-LANGU
    POPUP_TITLE = TEXT
    - = 
    001 = 
    START_COLUMN = 10
    START_ROW = 3
    TEXT_OBJECT = 'YAKBC405_F1_HELP_TEXT'
    * YAKBC405_F1_HELP_TEXT in Transaktion SE61 angelegt: = 
    *                       Dokumentenklasse: Text im Dialog = 
  EXCEPTIONS
    TEXT_NOT_FOUND = 1
.
IF SY-SUBRC = 1.
  WRITE 'Es konnte kein Hilfetext gefunden werden' ( 002 ).
ENDIF.
GET PARAMETER ID SPFLI FIELD .
WRITE SPFLI-CARRID.
COLOR COL_HEADING NO-GAP , SPFLI-CONNID COLOR COL_HEADING , /20 SPFLI-CITYFROM COLOR COL_NORMAL INTENSIFIED ON , SPFLI-CITYTO COLOR COL_NORMAL INTENSIFIED OFF , / ( 20 ) SPFLI-DEPTIME UNDER SPFLI-CITYFROM COLOR COL_NORMAL INTENSIFIED ON USING EDIT MASK '__:__' , ( 20 ) SPFLI-ARRTIME UNDER SPFLI-CITYTO COLOR COL_NORMAL INTENSIFIED OFF USING EDIT MASK '__:__'.
*&---------------------------------------------------------------------*
*&      Module  STATUS_0100  OUTPUT
*&---------------------------------------------------------------------*
*       text
*----------------------------------------------------------------------*
MODULE STATUS_0100 OUTPUT.
SET PF-STATUS 'HELP'.
SET TITLEBAR 'HELP'.
ENDMODULE.
" STATUS_0100  OUTPUT
*&---------------------------------------------------------------------*
*&      Module  BACK  INPUT
*&---------------------------------------------------------------------*
*       text
*----------------------------------------------------------------------*
MODULE BACK INPUT.
SET SCREEN 0.
ENDMODULE.
" BACK  INPUT