*&---------------------------------------------------------------------*
*& Report  YAK_405_10_WITH_STATUS                                      *
*&                                                                     *
*&---------------------------------------------------------------------*
*&                                                                     *
*&                                                                     *
*&---------------------------------------------------------------------*
REPORT YAK_405_10_WITH_STATUS LINE-SIZE 80.
NODES : SPFLI , SFLIGHT.
TABLES SCARR.
CONSTANTS BLANK VALUE ' '.
CONSTANTS POS1 TYPE I VALUE 14.
CONSTANTS POS2 TYPE I VALUE 32.
CONSTANTS POS3 TYPE I VALUE 36.
DATA FREE_SEATS LIKE SFLIGHT-SEATSMAX.
DATA CARRIER LIKE SPFLI-CARRID.
DATA *     Variable for menu entry.
MENU_ENTRY ( 40 ).
GET PARAMETER ID SPFLI FIELD FIELDS.
CARRID CONNID CITYFROM CITYTO DEPTIME ARRTIME.
FORMAT COLOR COL_NORMAL INTENSIFIED OFF.
WRITE /.
SPFLI-CARRID COLOR COL_KEY , 6 SPFLI-CONNID COLOR COL_KEY , 15 SPFLI-CITYFROM , SPFLI-CITYTO , SPFLI-DEPTIME , 70 SPFLI-ARRTIME , AT SY-LINSZ BLANK.
HIDE : SPFLI-CARRID , SPFLI-CONNID.
END-OF-SELECTION.
MENU_ENTRY = 'Zusatzinfo''s zur Fluggesellschaft ' ( 004 ).
*   Set status BASE
SET PF-STATUS 'BASE'.
SET TITLEBAR 'BAS'.
CLEAR SPFLI-CARRID.
AT USER-COMMAND.
CASE SY-UCOMM.
ENDCASE.
TOP-OF-PAGE.
DURING LINE-SELECTION.
CASE SY-PFKEY.
  WHEN 'VL1'.
    FORMAT COLOR COL_TOTAL.
    WRITE SPFLI-CARRID SPFLI-CONNID.
    FORMAT COLOR COL_HEADING.
    WRITE /.
    'Flugdatum' ( 001 ) , AT POS1 ' Flugpreis' ( 002 ) , AT POS2 'freie Plätze' ( 003 ) , AT SY-LINSZ BLANK.
    ULINE AT ( SY-LINSZ ).
ENDCASE.