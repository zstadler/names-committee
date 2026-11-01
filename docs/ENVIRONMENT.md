# סביבת-עבודה, הרצה ומלכודות

נקודת-הכניסה לתיעוד: [`PROJECT_NOTES.md`](../PROJECT_NOTES.md).

## מה שאיננו בריפו וצריך להשיג מחדש בכל סביבת-עבודה
1. **קובצי-ה-PDF של הגיליונות** - `samples/` נמצא ב-`.gitignore`. הכתובות נמצאות בעמודה
   "קישור ישיר לעמוד ההודעה" ב-`data/stage1_input_clean.csv`. ראו "הורדת PDF" למטה.
2. **מודל ה-OCR העברי** `heb.traineddata` (~5.4MB) - ראו "התקנת Hebrew tesseract" למטה,
   כולל המלכודת שבה הורדה-שנכשלה מחזירה קובץ-שגיאה זעיר והצינור נותן 0 מילים **בשקט**.
3. **`scan/`** - תוצרי-ביניים (רינדורים, חיתוכים, JSON לכל עמוד); נוצרים מחדש בכל הרצה.
4. **הטופונומסטיקון** (לשלב ההשוואה) - PDF של 232 עמ' (~220MB), לא בריפו; הועלה בעבר כקובץ
   מצורף לשיחה.

## הרצה
```bash
./run_batch_600dpi --pdf=samples/booklet_2633.pdf --booklet=2633 --jobs=2 --budget=3000 \
  --stage1=data/stage1_input_clean.xlsx
./build_v3_output --booklet=2633 --date=1980-06-10 --tag=run --out=.
```
- **`--stage1` חובה כשמריצים מהריפו**: ברירת-המחדל היא `stage1_input_clean.xlsx` בתיקייה הנוכחית.
- מבנה ההרצה ונימוקיו (קובץ-לעמוד, המשך-אחרי-הפסקה, מקביליות): [`DECISIONS.md`](DECISIONS.md).

## הורדת PDF
שני hosts מגישים את אותם מסמכים באותו path: `free-justice.openapi.gov.il` (`/free/moj/...`, כפי
שמופיע ב-URL-ים המקוריים) ו-`pub-justice.openapi.gov.il` (`/pub/moj/...`). **הזמינות שלהם משתנה
עם הזמן ובין סביבות** (פעם רק `pub-justice` עבד; ב-9.9.2026 `pub-justice` החזיר HTTP 500 עם גוף
JSON קצר ו-`free-justice` עבד). **כלל:** לנסות את שניהם, ולאמת שהתוצאה היא PDF אמיתי (`pdfinfo`,
מספר-עמודים תואם לעמודה "סה"כ עמודים בגיליון"), לא להסתמך על קוד-HTTP בלבד.

## התקנת Hebrew tesseract (נדרש בכל סביבת עבודה חדשה)
```bash
curl -sL -o /tmp/heb.traineddata "https://raw.githubusercontent.com/tesseract-ocr/tessdata/main/heb.traineddata"
cp /tmp/heb.traineddata /usr/share/tesseract-ocr/5/tessdata/heb.traineddata
```
**חובה לאמת גודל-קובץ אחרי ההורדה (~5.4MB).** הכתובת `github.com/.../raw/main/...` החזירה פעם
**גוף-שגיאה של 378 בתים** עם קוד-הצלחה, והקובץ ה"מותקן" גרם ל-`Failed loading language 'heb'` -
כלומר **0 מילים בכל OCR, בלי הודעת-שגיאה בצינור עצמו**. להשתמש ב-`raw.githubusercontent.com`
ולבדוק `ls -la`.
**אזהרה על חלופת-apt:** `apt-get install tesseract-ocr-heb` מתקין מודל **ישן** (961KB, 2019/legacy).
הוא עובד, אבל אינו המודל שכל ערכי-הסף במסמך הזה כוילו מולו.

## דחיפה ל-GitHub מסשן Cowork - מלכודות
- **`git push` נחסם בסשן**: ה-proxy של git מחזיר 403 כי הריפו אינו ב"מקורות" המורשים של הסשן, ובסשן
  Cowork אין דרך להוסיף אותו. הדחיפה היא דרך ה-GitHub connector בלבד, או מהמחשב של המשתמש (`git am` לקובץ-patch).
- **ה-connector דורש את ה-GitHub App "Claude Github MCP Connector"** מותקן על החשבון שבבעלותו הריפו,
  עם Contents read & write. היא נפרדת מה-App "Claude" של Claude Code. בלעדיה כל כתיבה מחזירה
  `403 Resource not accessible by integration`.
- **ה-connector שולח כל קובץ שהשתנה במלואו**: שינוי של שורה בקובץ-תיעוד עברי גדול איטי (כל תו עברי
  נשלח כרצף-בריחה בן 6 תווים). שינויי-קוד בלבד מהירים.
- **רצפי-בריחה של backslash-u עם 4 ספרות-hex מפוענחים בדרך**: ה-connector הפך אותם לתו עצמו (מקף-en
  במקום רצף-הבריחה), גם בשתי דחיפות-תיקון. לכן בקוד כותבים תווים מיוחדים כ-`\N{NAME}` - ASCII טהור
  שה-connector לא משנה.
- **ה-connector לא שומר הרשאות-קובץ**: קובץ-הרצה (`build_v3_output`, `run_batch_600dpi`) שנדחף דרכו
  יורד ל-100644, ויש להחזיר את ה-executable bit מהמחשב המקומי.
- **אחרי כל דחיפה**: להשוות blob-SHA **וגם** mode של כל קובץ מול העותק המקומי (`git ls-tree`).
