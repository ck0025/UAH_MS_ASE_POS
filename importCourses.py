import json
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen


urls = [
    "https://catalog.uah.edu/#/courses?group=Mechanical%20%26%20Aerospace%20Engineering",
    "https://catalog.uah.edu/#/courses?group=Industrial%20%26%20Systems%20Engineering",
    "https://catalog.uah.edu/#/courses?group=Atmospheric%20%26%20Earth%20Science",
    "https://catalog.uah.edu/#/courses?group=Biological%20Sciences",
    "https://catalog.uah.edu/#/courses?group=Biotechnology%20Science%20%26%20Engineering",
    "https://catalog.uah.edu/#/courses?group=Chemical%20Engineering",
    "https://catalog.uah.edu/#/courses?group=Chemistry",
    "https://catalog.uah.edu/#/courses?group=Civil%20Engineering",
    "https://catalog.uah.edu/#/courses?group=Computer%20Engineering",
    "https://catalog.uah.edu/#/courses?group=Computer%20Science",
    "https://catalog.uah.edu/#/courses?group=Electrical%20Engineering",
    "https://catalog.uah.edu/#/courses?group=Engineering%20Management",
    "https://catalog.uah.edu/#/courses?group=Materials%20Science",
    "https://catalog.uah.edu/#/courses?group=Mathematics",
    "https://catalog.uah.edu/#/courses?group=Optical%20Science%20Engineering",
    "https://catalog.uah.edu/#/courses?group=Physics",
    "https://catalog.uah.edu/#/courses?group=Space%20Science",
]

API_BASE = "https://uahcm.kuali.co/api/v1/catalog"
OUTPUT_FILE = "catalog.js"
DETAIL_WORKERS = 12


def load_json(api_url):
    with urlopen(api_url, timeout=30) as response:
        return json.load(response)


def get_course_group(catalog_url):
    fragment = urlparse(catalog_url).fragment
    query = urlparse(fragment).query
    return parse_qs(query).get("group", [""])[0]


def split_course_id(catalog_course_id):
    match = re.fullmatch(r"([A-Z]+)(.+)", catalog_course_id)
    if not match:
        return catalog_course_id, ""
    return match.groups()


def format_credits(credits):
    if not credits:
        return None

    value = credits.get("value")
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)

    if isinstance(value, dict):
        min_credits = value.get("min")
        max_credits = value.get("max")
        if min_credits == max_credits:
            return min_credits
        if min_credits is not None and max_credits is not None:
            return f"{min_credits}-{max_credits}"

    credit_range = credits.get("credits", {})
    min_credits = credit_range.get("min")
    max_credits = credit_range.get("max")
    if min_credits == max_credits:
        return min_credits
    if min_credits is not None and max_credits is not None:
        return f"{min_credits}-{max_credits}"

    return None


def course_sort_key(course):
    match = re.fullmatch(r"([A-Z]+)(\d+)([A-Z]*)", course["__catalogCourseId"])
    if not match:
        return (course["__catalogCourseId"], 0, "")
    subject, number, suffix = match.groups()
    return (subject, int(number), suffix)


def is_graduate_course(course):
    match = re.fullmatch(r"[A-Z]+(\d+)[A-Z]*", course["__catalogCourseId"])
    return bool(match and match.group(1)[0] in {"5", "6", "7"})


def build_course_entry(catalog_id, course):
    course_detail = load_json(f"{API_BASE}/course/{catalog_id}/{course['pid']}")
    department, course_number = split_course_id(course["__catalogCourseId"])

    return department, course_number, {
        "title": course_detail.get("title", course["title"]),
        "credits": format_credits(course_detail.get("credits")),
    }


def download_courses():
    groups = {get_course_group(catalog_url) for catalog_url in urls}
    groups.discard("")
    if len(groups) != len(urls):
        raise ValueError("One or more catalog URLs did not include a course group.")

    current_catalog = load_json(f"{API_BASE}/public/catalogs/current")
    catalog_id = current_catalog["_id"]
    all_courses = load_json(f"{API_BASE}/courses/{catalog_id}?q=")

    matching_courses = [
        course
        for course in all_courses
        if course.get("subjectCode", {}).get("description") in groups
        and is_graduate_course(course)
    ]

    courses = {}
    sorted_courses = sorted(matching_courses, key=course_sort_key)
    with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as executor:
        for department, course_number, course_entry in executor.map(
            lambda course: build_course_entry(catalog_id, course),
            sorted_courses,
        ):
            courses.setdefault(department, {})[course_number] = course_entry

    return courses


def main():
    courses = download_courses()
    course_count = sum(len(course_numbers) for course_numbers in courses.values())

    with open(OUTPUT_FILE, "w", encoding="utf-8") as output:
        output.write(f"const catalog = {json.dumps(courses, indent=4)};\n")

    print(f"Success: saved {course_count} courses to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
