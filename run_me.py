import requests
from bs4 import BeautifulSoup
import logging
import string
import datetime
import re
import pdb
from mongoengine import *
from selenium import webdriver
from selenium.webdriver.chrome.service import Service


class Article(Document):
    platform = StringField()
    uid = StringField()
    url = StringField()
    tags = ListField(StringField())
    pdf_url = StringField()
    other_url = StringField()
    title = StringField()
    abstract = StringField()
    authors = ListField(StringField())
    subjects = ListField(StringField())
    submitted_date = DateField()
    announced_date = DateField()
    comments = StringField()
    cite_as = ListField(StringField())
    related_doi = StringField()
    references_and_citations = ListField(StringField())


class BaseScraper:
    use_debug = True
    max_retry_cnt = 3
    mongo_uri = "mongodb+srv://admin:8teW6y6NsfwA@arxiv.pjzernq.mongodb.net/?retryWrites=true&w=majority&appName=arxiv"

    def __init__(self):
        try:
            connect(host=self.mongo_uri)
            self.session = requests.Session()
            self.config_log()
        except Exception as e:
            self.print_out(f"init: {e}")

    def get_driver(self):
        service = Service(executable_path='./chromedriver.exe')
        options = webdriver.ChromeOptions()
        # options.add_argument('--headless=new')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('excludeSwitches', ['enable-logging'])
        options.add_experimental_option('useAutomationExtension', False)
        return webdriver.Chrome(service=service, options=options)

    def get_cookies(self):
        cookies = []
        for cookie in self.driver.get_cookies():
            try:
                cookies.append(f"{cookie['name']}={cookie['value']}")
            except:
                pass
        return "; ".join(cookies)

    def get_value(self, element, is_multiple=False):
        try:
            if is_multiple:
                return element.get_text().split("\n")
            return self.validate(element.get_text(strip=True))
        except:
            return ""

    def get_prop(self, element, prop):
        try:
            return self.validate(element[prop])
        except:
            return ""

    def get_value_list(self, elements, prop=None):
        try:
            values = []
            for ele in elements:
                if prop:
                    values.append(self.get_prop(ele, prop))
                else:
                    values.append(self.get_value(ele))

            return values
        except:
            return ""

    def validate(self, item):
        try:
            if item == None:
                item = ''
            if type(item) == int or type(item) == float:
                item = str(item)
            if type(item) == list:
                item = ' '.join(item)
            item = item.strip()
            if item.endswith(";") or item.endswith("."):
                item = item[:-1]
            return item
        except:
            return ""

    def eliminate_space(self, items):
        rets = []
        for item in items:
            item = self.validate(item)
            if item.lower() not in ['', ',', 'submitted', 'originally announced']:
                rets.append(item)
        return rets

    def config_log(self):
        logging.basicConfig(
            filename=f"history.log",
            format='%(asctime)s %(levelname)-s %(message)s',
            level=logging.INFO,
            datefmt='%Y-%m-%d %H:%M:%S')

    def print_out(self, value):
        if self.use_debug:
            print(value)
        else:
            logging.info(value)


class ArxivScraper(BaseScraper):
    name = "arxiv.org"
    base_url = "https://arxiv.org"
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Cookie": "browser=104.129.55.3.1714548521015336; arxiv-search-parameters={}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    }

    def run(self):
        response = self.session.get("https://arxiv.org/search/advanced", headers=self.headers)
        soup = BeautifulSoup(response.text, features="xml")
        subject_list = []
        for element in soup.find_all(class_="checkbox")[:-1]:
            subject_list.append(self.get_prop(element.input, "id"))

        try:
            current_year = datetime.date.today().year + 1
            for subject in subject_list:
                for year in range(2010, current_year):
                    for alpha in string.ascii_lowercase:
                        url = f"https://arxiv.org/search/advanced?advanced=&terms-0-operator=AND&terms-0-term={alpha}&terms-0-field=all&{subject}=y&classification-physics_archives=all&classification-include_cross_list=include&date-filter_by=specific_year&date-year={year}&date-from_date=&date-to_date=&date-date_type=submitted_date&abstracts=show&size=200&order=-announced_date_first"
                        self.parse_page(url)
        except Exception as e:
            self.print_out(f"run: {e}")

    def parse_page(self, url, retry_cnt=0):
        try:
            response = self.session.get(url, headers=self.headers)
            soup = BeautifulSoup(response.text, features="xml")
            articles = soup.find_all(class_="arxiv-result")
            if len(articles) == 0 and retry_cnt > self.max_retry_cnt:
                exit(0)

            for article in articles:
                self.parse_article(article)

            try:
                next_page_url = soup.find("a", class_="pagination-next")
                if next_page_url:
                    self.parse_page(f"{self.base_url}{next_page_url['href']}")
            except:
                start_from = int(url.split("&start=")[1]) + 200
                next_page_url = f"{'&'.join(url.split('&')[:-1])}&start={start_from}"
                self.parse_page(f"{self.base_url}{next_page_url}", retry_cnt+1)
        except Exception as e:
            self.print_out(f"parse_page: {e}")
            if retry_cnt > self.max_retry_cnt:
                return
            self.parse_page(url, retry_cnt+1)

    def parse_article(self, article):
        try:
            uid = self.get_value(article.find(class_="list-title is-inline-block").a)
            articles = Article.objects(uid=uid)
            if len(articles) > 0:
                return

            url = self.get_prop(article.find(class_="list-title is-inline-block").a, "href")
            response = self.session.get(url, headers=self.headers)
            soup = BeautifulSoup(response.text, features="xml")

            dates = self.eliminate_space(article.find("p", class_="is-size-7").get_text("|", strip=True).split("|"))
            if len(dates) < 2:
                dates.append("")

            submitted_date, announced_date = None, None
            try:
                submitted_date = datetime.datetime.strptime(dates[0], "%d %B, %Y")
                announced_date = datetime.datetime.strptime(dates[-1], "%B %Y")
            except:
                pass

            pdf_url, other_url = "", ""
            for resource in article.find_all("p", class_="list-title is-inline-block"):
                r_url = self.get_prop(resource.a, "href")
                if "/pdf/" in r_url:
                    pdf_url = r_url
                if "/format/" in r_url:
                    other_url = r_url

            Article(
                platform=self.name,
                uid=uid,
                url=url,
                tags=self.eliminate_space(self.get_value(article.find(class_="tags is-inline-block"), True)),
                pdf_url=pdf_url,
                other_url=other_url,
                title=self.get_value(article.find(class_="title is-5 mathjax")),
                abstract=self.get_value(soup.find(class_="abstract mathjax")),
                authors=self.get_value_list(article.find_all(href=re.compile("searchtype=author"))),
                subjects=self.eliminate_space(self.get_value(soup.find(class_="tablecell subjects")).split(";")),
                submitted_date=submitted_date,
                announced_date=announced_date,
                comments=self.get_value(article.find(class_="comments is-size-7")).replace("Comments:", ""),
                cite_as=self.eliminate_space([self.get_value(soup.find("td", class_="tablecell arxivid")), self.get_value(soup.find("td", class_="tablecell arxividv")), self.get_value(soup.find("td", class_="tablecell arxivdoi").a)]),
                related_doi=self.get_value(soup.find("td", class_="tablecell doi")),
                references_and_citations=self.eliminate_space(self.get_value(soup.find(class_="extra-ref-cite"), True))
            ).save()
            self.print_out(f"success: {uid}")
        except Exception as e:
            self.print_out(f"parse_article: {e}")


class IeeeScraper(BaseScraper):
    name = "ieeexplore.ieee.org"
    base_url = "https://ieeexplore.ieee.org"
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Cookie": "AWSALBAPP-1=_remove_; AWSALBAPP-2=_remove_; AWSALBAPP-3=_remove_; osano_consentmanager_uuid=8206e95a-cfba-4288-8756-305f53c3cc75; osano_consentmanager=CYCBIXsdKfAsQsHrad92HR36nYkTuP2YclrYmH40IKDvwJXJxMONUbCu23vlpsJ5NlQ4lqll-SJoYa9aKmY9NhS0PjQY8807f7TiLEuRarAAOF2zoRsQYnL6C78vyz0KNhuSU-ON5cfg8QBC3PiS0nAW29nHwimS5iDx6VOnJ4kiD7m2LXht-QuGbeFjx8G-chHJkhVWFTqgNRgJMcCz6WT3e3YuTSNm3es3EmOT73XHU0U-hhUSQQy3gCIXGZyEDk_IBxVjOleEaPi2WcyMJXUnLUM2mNptahvOug==; hum_ieee_visitor=50bb7454-db0d-44aa-a8a4-a133e41e1a04; s_ecid=MCMID%7C49920006945930573774287454586912502744; _cc_id=11b310d8d5e746bb04ee415ae913118f; panoramaId_expiry=1715279576414; panoramaId=d813db1a4eb3e82d0ec17da6db82a9fb927a83c9259986c5de1396305a367968; panoramaIdType=panoDevice; ipCheck=104.129.55.3; AMCVS_8E929CC25A1FB2B30A495C97%40AdobeOrg=1; s_cc=true; s_fid=237FECEEBD9CE903-0706DC9A3899051B; s_cc=true; s_sq=ieeexplore.prod%3D%2526c.%2526a.%2526activitymap.%2526page%253DSearch%252520Results%2526link%253DAffiliation%2526region%253DxplMainContent%2526pageIDType%253D1%2526.activitymap%2526.a%2526.c%2526pid%253DSearch%252520Results%2526pidt%253D1%2526oid%253DAffiliation%2526oidt%253D3%2526ot%253DSUBMIT; JSESSIONID=B475BD095513C626915DF5029B52D449; WLSESSION=1409380874.47873.0000; AMCV_8E929CC25A1FB2B30A495C97%40AdobeOrg=359503849%7CMCIDTS%7C19852%7CMCMID%7C49920006945930573774287454586912502744%7CMCAAMLH-1715843013%7C7%7CMCAAMB-1715843013%7CRKhpRz8krg2tLO6pguXWp5olkAcUniQYPHaMWWgdJ3xzPWQmdj0y%7CMCOPTOUT-1715245413s%7CNONE%7CMCAID%7CNONE%7CvVersion%7C5.0.1; TS016349ac=01f15fc87c1f6e9ce920ea45c50acdcac7dab311bbe569a2e45ef260f02e2de50cf50e14fb6c3c2ce3559dfc8bcacb22c3048246cb; s_sq=%5B%5BB%5D%5D; AWSALBAPP-0=AAAAAAAAAAAaGIZ3vATynEu6pT75JyAA5apHba0pgPGdTevSeXiP9AW/ThwSDf9aKjY1ryPfScdpBnaPev1ZfW6hOYbZwtJA+5PLA6k5HdO+sPiqK6yDYTLdpzVaugTKqwr+pf/x/CQLhYdvjATYfneiZRIuegO0ANDaCpxI5pxqy21NZwja2O44uwZ40nN8ycOtk+hRSTs/YQKzAFg4GQ==; TSaf720a17029=0807dc117eab2800bc23b8086aca0e14ad7357b6909650a96fa3258867496898fd4030675a7d87ea040ce4966f27ef6c; TS8b476361027=0807dc117eab200075c003f736a19ae97bb99abf763352349aa0def06fa52e5564adae3844c62cbf0830e070d8113000967853f4af5d30cc24ea7a23d58975abf20e56c51d0e8c2dba2d6325d865efa6ed17d9d36e97fa5f02dfbd1005579d3b; utag_main=v_id:018f597ac975000e9a3c9f34559e0506f003306700978$_sn:3$_se:6$_ss:0$_st:1715240391841$vapi_domain:ieeexplore.ieee.org$ses_id:1715238209151%3Bexp-session$_pn:3%3Bexp-session",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    }

    def run(self):
        try:
            self.driver = self.get_driver()
            self.driver.get("https://ieeexplore.ieee.org/search/searchresult.jsp")
            self.cookies = self.get_cookies()
            page_number = 1
            while True:
                self.parse_page(page_number)
                page_number += 1
        except Exception as e:
            self.print_out(f"run: {e}")

    def parse_page(self, page_number, retry_cnt=0):
        try:
            post_script = '''
                return fetch("https://ieeexplore.ieee.org/rest/search", {
                    "headers": {
                        "Accept": "application/json, text/plain, */*",
                        "Content-Type": "application/json",
                        "Cookie": "cookies",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    },
                    "body": JSON.stringify({"highlight":true,"returnType":"SEARCH","pageNumber": page_number,"rowsPerPage":"100","returnFacets":["ALL"]}),
                    "method": "POST",
                })
                .then(res => res.json())
                .catch(error => console.error("Error:", error))
            '''
            post_script = post_script.replace("page_number", f"{page_number}")
            post_script = post_script.replace("cookies", f"{self.cookies}")
            response = self.driver.execute_script(post_script)
            articles = response.get("records", [])
            if len(articles) == 0:
                exit(0)

            for article in articles:
                self.parse_article(article)
        except Exception as e:
            self.print_out(f"parse_page: {e}")
            if retry_cnt > self.max_retry_cnt:
                return
            self.parse_page(page_number, retry_cnt+1)

    def parse_article(self, article):
        try:
            uid = article.get("doi")
            articles = Article.objects(uid=uid)
            if len(articles) > 0:
                return

            date = None
            try:
                date = datetime.datetime.strptime(article.get("publicationDate", "").split("-")[-1].replace(".", ""), "%d %B %Y")
            except:
                pass

            Article(
                platform=self.name,
                uid=uid,
                url=f"{self.base_url}{article.get('documentLink')}",
                pdf_url=f"{self.base_url}{article.get('pdfLink')}",
                other_url=article.get('rightsLink'),
                title=article.get("articleTitle"),
                abstract=article.get("abstract"),
                authors=[author.get("preferredName") for author in article.get("authors")],
                subjects=[article.get("displayPublicationTitle")],
                submitted_date=date,
                announced_date=date,
                cite_as=[f"Papers ({article.get('citationCount')})", f"Patents ({article.get('patentCitationCount')})"],
            ).save()
            self.print_out(f"success: {uid}")
        except Exception as e:
            self.print_out(f"parse_article: {e}")


if __name__ == '__main__':
    ArxivScraper().run()
    # IeeeScraper().run()
