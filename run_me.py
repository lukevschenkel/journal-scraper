import requests
from bs4 import BeautifulSoup
import logging
import string
import datetime
import pdb
from mongoengine import *

class Article(Document):
    uid = StringField()
    url = StringField()
    tags = ListField()
    resource = ListField()
    title = StringField()
    abstract = StringField()
    authors = ListField()
    subjects = StringField()
    submitted_date = StringField()
    announced_date = StringField()
    comments = StringField()
    cite_as = ListField()
    related_doi = StringField()
    references_and_citations = ListField()

class Main:
    name = "arxiv"
    domain = "https://arxiv.org"
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Cookie": "browser=104.129.55.3.1714548521015336; arxiv-search-parameters={}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    }
    use_debug = True
    mongo_uri = "mongodb+srv://admin:8teW6y6NsfwA@arxiv.pjzernq.mongodb.net/?retryWrites=true&w=majority&appName=arxiv"
    max_retry_cnt = 3

    def __init__(self):
        try:
            self.session = requests.Session()
            connect(host=self.mongo_uri)
            self.config_log()
            self.start_requests()
        except Exception as e:
            self.print_out(f"init: {e}")

    def start_requests(self):
        response = self.session.get("https://arxiv.org/search/advanced", headers=self.headers)
        soup = BeautifulSoup(response.text, features="xml")
        subject_list = []
        for element in soup.select("div[class='columns is-baseline'] div[class='checkbox'] input")[:-1]:
            subject_list.append(self.get_prop(element, "id"))

        try:
            current_year = datetime.date.today().year + 1
            for subject in subject_list:
                for year in range(1991, current_year):
                    for alpha in string.ascii_lowercase:
                        url = f"https://arxiv.org/search/advanced?advanced=&terms-0-operator=AND&terms-0-term={alpha}&terms-0-field=all&{subject}=y&classification-physics_archives=all&classification-include_cross_list=include&date-filter_by=specific_year&date-year={year}&date-from_date=&date-to_date=&date-date_type=submitted_date&abstracts=show&size=200&order=-announced_date_first"
                        self.parse_page(url)
        except Exception as e:
            self.print_out(f"start_requests: {e}")

    def parse_page(self, url, retry_cnt=0):
        try:
            response = self.session.get(url, headers=self.headers)
            soup = BeautifulSoup(response.text, features="xml")
            articles = soup.select("li[class='arxiv-result']")
            for article in articles:
                self.parse_article(article)

            next_page_url = soup.select_one("a[class='pagination-next']")
            if next_page_url:
                self.parse_page(f"{self.domain}{next_page_url['href']}")

        except Exception as e:
            self.print_out(f"parse_page: {e}")
            if retry_cnt > self.max_retry_cnt:
                return
            self.parse_page(url, retry_cnt+1)

    def parse_article(self, article):
        try:
            uid = self.get_value(article.select_one("p[class='list-title is-inline-block'] a"))
            articles = Article.objects(uid=uid)
            if len(articles) > 0:
                return

            url = self.get_prop(article.select_one("p[class='list-title is-inline-block'] a"), "href")
            response = self.session.get(url, headers=self.headers)
            soup = BeautifulSoup(response.text, features="xml")

            dates = self.eliminate_space(article.select_one("p[class='is-size-7']").get_text("|", strip=True).split("|"))
            if len(dates) < 2:
                dates.append("")

            details = {
                "uid": uid,
                "url": url,
                "tags": self.get_value_list(article.select_one("div[class='tags is-inline-block'] span")),
                "resource": self.get_value_list(article.select("p[class='list-title is-inline-block'] span a"), "href"),
                "title": self.get_value(article.select_one("p[class='title is-5 mathjax']")),
                "abstract": self.get_value(soup.select_one("blockquote[class='abstract mathjax']")),
                "authors": self.get_value_list(article.select("p[class='authors'] a")),
                "subjects": self.get_value(soup.select_one("td[class='tablecell subjects']")),
                "submitted_date": dates[0],
                "announced_date": dates[-1],
                "comments": self.get_value(article.select_one("p[class='comments is-size-7'] span[class='has-text-grey-dark mathjax']")),
                "cite_as": self.eliminate_space([self.get_value(soup.select_one("td[class='tablecell arxivid']")), self.get_value(soup.select_one("td[class='tablecell arxividv']")), self.get_value(soup.select_one("td[class='tablecell arxivdoi'] a"))]),
                "related_doi": self.get_value(soup.select_one("td[class='tablecell doi']")),
                "references_and_citations": self.get_value_list(soup.select("div[class='extra-ref-cite'] ul li"))
            }

            Article(**details).save()

            self.print_out(f"success: {details['uid']}")
        except Exception as e:
            self.print_out(f"parse_article: {e}")

    def get_value(self, element):
        try:
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


if __name__ == '__main__':
    Main()
