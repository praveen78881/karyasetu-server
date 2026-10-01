# Deploying KaryaSetu to the cloud (free, ~10 minutes)

After this, the app runs 24/7 at your own address like
`https://yourname.pythonanywhere.com` — **your laptop can stay off**.
Teammates use it from anywhere, install it on their phones, and full
offline mode works (HTTPS enables it).

The only thing that needs a human is creating the free account (email
verification). Everything else is prepared: upload the ZIP, paste one
config block, done.

---

## Step-by-step: PythonAnywhere (free "Beginner" plan)

1. **Sign up** at https://www.pythonanywhere.com → *Pricing & signup* →
   *Create a Beginner account* (free, no card). Your username becomes your
   app's address: `https://USERNAME.pythonanywhere.com`.

2. **Upload the project**: go to the **Files** tab → *Upload a file* →
   upload `karyasetu-deploy.zip` (it's at `C:\WorkHub\karyasetu-deploy.zip`).

3. **Unpack and install**: open the **Consoles** tab → *Bash*, then run:

   ```bash
   unzip karyasetu-deploy.zip -d karyasetu
   cd karyasetu
   pip3 install --user -r requirements.txt
   ```

4. **Create the web app**: **Web** tab → *Add a new web app* →
   accept the domain → **Manual configuration** → pick the newest Python
   version offered.

5. On the Web tab, set **Source code** to:

   ```
   /home/USERNAME/karyasetu
   ```

6. Click the **WSGI configuration file** link on the Web tab, delete its
   contents, and paste this (replace `USERNAME`, and put any long random
   text as the secret key):

   ```python
   import os, sys
   sys.path.insert(0, '/home/USERNAME/karyasetu')
   os.environ['SECRET_KEY'] = 'paste-a-long-random-string-here-keep-it-private'
   os.environ['HTTPS'] = '1'
   from app import app as application
   ```

7. Still on the Web tab, under **Static files** add one mapping:

   | URL | Directory |
   |---|---|
   | `/static/` | `/home/USERNAME/karyasetu/static` |

8. Press the green **Reload** button, then open
   `https://USERNAME.pythonanywhere.com` — you'll see the
   **Set up your workspace** page. Create your manager account and add
   your team members from the Team page.

## Give it to your team

- **Phones/laptops (recommended):** send them the URL. On Android Chrome:
  menu → *Add to Home screen*. On iPhone Safari: Share → *Add to Home
  Screen*. On desktop: the install icon in the address bar. This is a full
  install with the KaryaSetu icon **and complete offline support**.
- **The APK:** anyone using `KaryaSetu.apk` opens it, presses Back →
  *Change server address*, and enters `https://USERNAME.pythonanywhere.com`.
  (Once you know your final URL, the APK can be rebuilt with it as the
  built-in default.)

## Using MySQL instead of SQLite (optional, also free)

The app runs on SQLite out of the box and that is fine for a small team —
the file persists on PythonAnywhere. If you want proper MySQL (as in the
original spec), the free plan includes a MySQL database:

1. **Databases** tab → set a MySQL password → create a database named
   `karyasetu` (it appears as `USERNAME$karyasetu`).
2. In the Bash console: `pip3 install --user pymysql`
3. Add one line to the WSGI configuration file (step 6), just above the
   `from app import ...` line, filling in your username and DB password:

   ```python
   os.environ['DATABASE_URL'] = 'mysql+pymysql://USERNAME:DBPASSWORD@USERNAME.mysql.pythonanywhere-services.com/USERNAME$karyasetu'
   ```
4. Press **Reload**. Tables are created automatically on first start.

## Free-plan notes

- Data (your SQLite database) is stored on their disk and **persists**.
- Visit pythonanywhere.com every ~3 months and press
  *"Run until 3 months from today"* on the Web tab to keep the free app
  alive (they email you a reminder).
- The free plan has no WebSocket support, so instant push is replaced by
  an automatic refresh every 30 seconds — the app detects this by itself;
  nothing to configure.
- To upload a new version later: upload the new ZIP, unzip over the old
  folder, press Reload.

## Alternative hosts

Any host that runs Flask works. If you outgrow the free plan:
- **Render.com** (free tier; add a persistent disk or switch
  `DATABASE_URL` to Postgres — SQLite on the free tier is wiped on restarts)
- Any VPS: `pip install -r requirements.txt && python app.py` behind an
  HTTPS reverse proxy, or gunicorn with `wsgi:application`.
