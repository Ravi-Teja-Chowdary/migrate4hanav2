REPORT ybapi.
TYPES typ_usr10 TYPE standard table of usr10.
TYPES typ_users TYPE STANDARD TABLE OF bapibname.
TYPES typ_return TYPE STANDARD TABLE OF bapiret2.
TYPES typ_profiles TYPE STANDARD TABLE OF bapiprof.
DATA it_return TYPE typ_return.
DATA it_profiles TYPE typ_profiles.
DATA it_usr10 TYPE typ_usr10.
DATA wa_profiles LIKE bapiprof.
DATA wa_usr10 LIKE usr10.
DATA wa_user LIKE bapibname.
DATA address LIKE bapiaddr3.
DATA logondata LIKE bapilogond.
DATA counter TYPE n.
DATA count_char.
( 2 ) , len type i , nrun type i.
PARAMETERS user LIKE bapibname.
PARAMETERS lower.
( 2 ) type n.
PARAMETERS upper.
( 2 ) type n.
SELECT-OPTIONS profiles FOR wa_profiles-bapiprof.
PARAMETERS pw LIKE bapipwd.
PARAMETERS dat1 LIKE logondata-gltgv DEFAULT sy-datum.
PARAMETERS dat2 LIKE logondata-gltgb DEFAULT 'SCRUBBED_STRING'.
PARAMETERS lgngrp LIKE logondata-class DEFAULT 'SCRUBBED_STRING'.
nrun = upper - lower + 1.
IF nrun < 0.
  WRITE /.
  'SCRUBBED_STRING'.
  EXIT.
ENDIF.
logondata-gltgv = dat1.
logondata-gltgb = dat2.
logondata-ustyp = 'SCRUBBED_STRING'.
logondata-class = lgngrp.
len = strlen ( user ).
counter = lower - 1.
SELECT *
  FROM usr10
  INTO TABLE it_usr10
  WHERE profn in profiles
.
LOOP AT it_usr10 INTO wa_usr10.
  wa_profiles-BAPIPROF = wa_usr10-profn.
  APPEND wa_profiles TO it_profiles.
ENDLOOP.
DO nrun times.
  counter = counter + 1.
  WRITE counter to count_char right-justified.
  REPLACE 'SCRUBBED_STRING' IN with WITH .
  'SCRUBBED_STRING' into count_char.
  user + len = count_char.
  CALL FUNCTION 'SCRUBBED_STRING'
    EXPORTING
      username = user
      logondata = logondata
      password = pw
      address = address
    TABLES
      return = it_return
  .
  LOOP AT it_profiles INTO wa_profiles.
    CALL FUNCTION 'SCRUBBED_STRING'
      EXPORTING
        username = user
      TABLES
        profiles = it_profiles
        return = it_return
    .
  ENDLOOP.
ENDDO.