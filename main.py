import sys
import datetime
import re
import sqlite3
import sys
import threading
import time
import urllib.request
import undetected_chromedriver as uc
import tempfile

from PyQt5 import QtCore, QtWidgets
from PyQt5.Qt import Qt
from PyQt5.QtGui import QIcon, QPixmap, QFontDatabase, QFont
from bs4 import BeautifulSoup

from ui import Ui_MainWindow


class ProgramUI(QtWidgets.QMainWindow):
    def __init__(self):
        super(ProgramUI, self).__init__()

        # Lock ui initialization
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        # Fonts
        self.fontDB = QFontDatabase()
        self.fontDB.addApplicationFont(":/fonts/fonts/Montserrat-ExtraBold.ttf")

        # Scrapper
        self.scraper = uc.Chrome()
        self.scraper.minimize_window()

        self.isWindowDragging = False
        self.cursor_position = None
        self.cursor_position_global = None

        # Quit
        self.ui.close_button.clicked.connect(self.closeAll)

        # Sqlite
        def dict_factory(cursor, row):
            d = {}
            for idx, col in enumerate(cursor.description):
                d[col[0]] = row[idx]
            return d

        self.sql = sqlite3.connect(f'{tempfile.gettempdir()}\\ozon_prices.db', check_same_thread=False)
        self.sql.row_factory = dict_factory
        self.cursor = self.sql.cursor()

        self.cursor.execute('''
CREATE TABLE IF NOT EXISTS prices(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url VARCHAR,
  unix_datetime REAL,
  value INTEGER
);''')
        self.sql.commit()

        self.cursor.execute('''
CREATE TABLE IF NOT EXISTS last_links(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  unix_datetime REAL,
  url VARCHAR
);''')
        self.sql.commit()

        # UI Initialization
        self.ui.product_link.setPlaceholderText('Ссылка на продукт')
        self.ui.product_link.setText('')
        self.product_html = ''

        def updateEvery30Minutes():
            while True:
                time.sleep(1800)
                self.updateProductInfo()

        updateThread = threading.Thread(target=updateEvery30Minutes, daemon=True)
        updateThread.start()

        self.setWindowTitle("Ozon Prices")
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setWindowIcon(QIcon(":/icons/icons/ozon.png"))

        self.insertLastLink()

    def keyPressEvent(self, e):
        if e.key() == 16777220:
            if self.ui.product_link.hasFocus():
                threading.Thread(target=self.updateProductInfo, daemon=True).start()

    def mousePressEvent(self, event):
        self.cursor_position_global = event.globalPos()
        self.cursor_position = self.mapFromGlobal(self.cursor_position_global)
        self.isWindowDragging = True

    def mouseMoveEvent(self, event):
        if self.isWindowDragging:
            self.cursor_position_global = event.globalPos()

            geometry = self.geometry()
            self.setGeometry(self.cursor_position_global.x() - self.cursor_position.x(),
                             self.cursor_position_global.y() - self.cursor_position.y(),
                             geometry.width(),
                             geometry.height())

    def mouseReleaseEvent(self, event):
        self.isWindowDragging = False

    def closeAll(self):
        self.scraper.close()
        self.scraper.quit()
        self.close()

    def scrapeWebPage(self, url):
        self.scraper.get(url)
        time.sleep(3)
        self.product_html = self.scraper.page_source

    def updatePricesDynamic(self):
        try:
            self.cursor.execute("SELECT unix_datetime, value, url "
                                "FROM prices "
                                f"WHERE url = '{self.ui.product_link.text()}'"
                                f"ORDER BY unix_datetime DESC;")

            prices = self.cursor.fetchall()
        except Exception:
            pass
        else:
            for price in prices:
                dt = datetime.datetime.fromtimestamp(price["unix_datetime"])
                item = f'[{dt.strftime("%d.%m.%Y %H:%M:%S")}] {price["value"]}₽'
                self.ui.product_prices.addItem(item)

    def updateName(self):
        with open('index.html', mode='w', encoding='utf-8') as f:
            f.write(self.product_html)

        soup = BeautifulSoup(self.product_html, features="html.parser")
        name = soup.find("div", {"data-widget": "webProductHeading"})
        name = name.find("h1").text

        self.ui.product_name.setText(name)

    def updatePrice(self):
        soup = BeautifulSoup(self.product_html, features="html.parser")
        price = soup.find("div", {"data-widget": "webPrice"})
        price = price.find("span").text

        price_int = int(''.join(re.findall(r'\b\d+\b', price)))

        self.cursor.execute(f"INSERT INTO prices (unix_datetime, value, url) "
                            f"VALUES ({time.time()}, {price_int}, '{self.ui.product_link.text()}')")
        self.sql.commit()

        self.ui.product_price.setText(str(price_int) + ' ₽')

    def updateLastPrice(self):
        try:
            self.cursor.execute("SELECT unix_datetime, value, url "
                                "FROM prices "
                                f"WHERE unix_datetime = (SELECT MAX(unix_datetime) FROM prices) "
                                f"AND url = '{self.ui.product_link.text()}';")

            last_price = self.cursor.fetchone()['value']
        except Exception:
            self.ui.product_last_price.setText('-' + ' ₽')
        else:
            self.ui.product_last_price.setText(str(last_price) + ' ₽')

    def updateImage(self):
        soup = BeautifulSoup(self.product_html, features="html.parser")
        gallery = soup.find("div", {"data-widget": "webGallery"})
        image = gallery.find("img")['src']
        image_path = f'product_image.{image.split(".")[-1]}'

        urllib.request.urlretrieve(image, image_path)

        pixmap = QPixmap(image_path).scaled(150, 150, Qt.KeepAspectRatio)

        self.ui.product_image.setPixmap(pixmap)

    def insertLastLink(self):
        try:
            self.cursor.execute("SELECT unix_datetime, url "
                                "FROM last_links "
                                f"WHERE unix_datetime = (SELECT MAX(unix_datetime) FROM last_links);")

            last_link = self.cursor.fetchone()['url']
        except Exception:
            pass
        else:
            self.ui.product_link.setText(last_link)
            threading.Thread(target=self.updateProductInfo, daemon=True).start()

    def saveLink(self, url):
        self.cursor.execute(f"INSERT INTO last_links (unix_datetime, url) "
                            f"VALUES ({time.time()}, '{url}')")
        self.sql.commit()

    def updateProductInfo(self):
        try:
            url = self.ui.product_link.text()
            self.saveLink(url)
            self.scrapeWebPage(url)

            self.updateName()
            self.updateLastPrice()
            self.updatePricesDynamic()
            self.updatePrice()
            self.updateImage()

        except Exception as e:
            self.ui.product_name.setText(str(e))


app = QtWidgets.QApplication([])
a = ProgramUI()
a.show()

sys.exit(app.exec())
