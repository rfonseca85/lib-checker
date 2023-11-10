import requests
import config as c
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus
import re


def transform_url(original_url, type, branch):
    # Regular expression to extract necessary parts of the URL
    pattern = r"https://api\.bitbucket\.org/2\.0/repositories/([^/]+)/([^/]+)/src/[^/]+/(.*)"
    match = re.match(pattern, original_url)
    if match:
        # Extracting the components
        owner, repo, file_path = match.groups()

        # Constructing the new URL
        if type == 'filePath':
            new_url = f"https://bitbucket.org/{owner}/{repo}/src/{branch}/{file_path}"
        elif type == 'branch':
            new_url = f"https://api.bitbucket.org/2.0/repositories/{owner}/{repo}/refs/branches/{branch}"
        return new_url
    else:
        return "Invalid URL format"


def find_default_branch(api_path):
    for branch in c.list_branches:
        if requests.get(transform_url(api_path, 'branch', branch), auth=(
                c.bitbucket['username'], c.bitbucket['password'])).status_code == 200:
            break
    return branch


def parse_pom_dependencies(pom_content):
    # Parse the pom.xml content
    root = ET.fromstring(pom_content)

    # Define the namespace map to handle the default namespace used in pom.xml
    namespaces = {'m': 'http://maven.apache.org/POM/4.0.0'}

    # Get the properties from the pom.xml content
    properties = root.find('m:properties', namespaces)
    properties_dict = {}
    if properties is not None:
        for child in properties:
            tag = child.tag.replace('{' + namespaces['m'] + '}', '')  # Strip namespace
            properties_dict[tag] = child.text

    # Find all the dependency elements in the pom.xml content
    dependencies = root.findall(".//m:dependencies/m:dependency", namespaces)

    # Extract the groupId, artifactId, and version for each dependency
    dependency_list = []
    for dependency in dependencies:
        groupId = dependency.find('m:groupId', namespaces).text
        artifactId = dependency.find('m:artifactId', namespaces).text
        version_element = dependency.find('m:version', namespaces)
        if version_element is not None:
            # Resolve the version from properties if necessary
            version_text = version_element.text
            if version_text.startswith('${') and version_text.endswith('}'):
                property_name = version_text[2:-1]
                version = properties_dict.get(property_name, 'VERSION PROPERTY NOT FOUND')
            else:
                version = version_text
        else:
            version = 'VERSION NOT SPECIFIED'
        dependency_list.append(f"{groupId}:{artifactId}:{version}")

    return dependency_list


def parse_gradle_dependencies(gradle_content):
    # Extract variables defined in the ext block
    ext_variables = {}
    ext_block_match = re.search(r'ext \{([\s\S]*?)\}', gradle_content)
    if ext_block_match:
        ext_block = ext_block_match.group(1)
        for line in ext_block.split('\n'):
            var_match = re.match(r'\s*(\w+)\s*=\s*\'?([^\'\s]+)\'?', line)
            if var_match:
                ext_variables[var_match.group(1)] = var_match.group(2)

    # Dependency pattern to match common configurations with potential variable use
    dependency_patterns = [
        r"^\s*(implementation|api|compileOnly|runtimeOnly|classpath) ['\"]([\w\.-]+):([\w\.-]+)(:[\w\.-]+)?['\"]",
        # Add more patterns here as needed
    ]

    dependencies = []
    for pattern in dependency_patterns:
        regex = re.compile(pattern, re.MULTILINE)
        matches = regex.findall(gradle_content)
        for match in matches:
            config, group, artifact, version = match[:4]
            classifier = match[4] if len(match) == 5 else ''

            # Substitute variables in version and classifier
            version_var = re.match(r'\$(\w+)', version)
            classifier_var = re.match(r'\$(\w+)', classifier) if classifier else None
            if version_var and version_var.group(1) in ext_variables:
                version = ext_variables[version_var.group(1)]
            if classifier_var and classifier_var.group(1) in ext_variables:
                classifier = ':' + ext_variables[classifier_var.group(1)]
            else:
                classifier = classifier or ''
            dependency = f"{config}: {group}:{artifact}:{version}{classifier}"
            dependencies.append(dependency)

    return dependencies


def parse_dependencies(file_type, content):
    if file_type == "pom.xml":
        return parse_pom_dependencies(content)
    elif file_type == "build.gradle":
        return parse_gradle_dependencies(content)
    else:
        print("Type not supported, consider implement a parse function")


def check_libraries(search_query):
    files = []
    # Properly encode the search query to be used in a URL
    encoded_query = quote_plus(search_query)
    next_page = f"{c.bitbucket['base_url']}/{c.bitbucket['workspace']}/search/code?search_query={encoded_query}"

    # Loop through all pages of search results (all pagination)
    while next_page:
        response = requests.get(next_page, auth=(c.bitbucket['username'], c.bitbucket['password']))

        # Check if the response was successful
        if response.status_code == 200:
            search_results = response.json()
            for result in search_results['values']:
                # Skip if result is not the query type (eg: if not pom.xml or build.gradle)
                if search_query not in result['file']['path']:
                    continue
                # otherwise continue the process and try parse the document in a list of libraries
                libraries = []
                api_path = result['file']['links']['self']['href']
                libraries = parse_dependencies(search_query,
                                               requests.get(api_path, auth=(
                                                   c.bitbucket['username'], c.bitbucket['password'])).text)

                file = {
                    'name': result['file']['path'],
                    'api_path': api_path,
                    'path': transform_url(api_path, 'filePath', find_default_branch(api_path)),
                    'content': libraries
                }
                files.append(file)

            # Get the next page URL, if it exists
            next_page = search_results.get('next', None)
        else:
            print("Failed to search the repository:", response.status_code, response.text)
            next_page = None  # Stop if there's an error

    return files


import webbrowser

files = check_libraries('pom.xml')
# files = check_libraries('build.gradle')
for file in files:
    print('--------------------------------------------------------------------------------------------')
    # print('File Name = ' + file['name'])
    # print('File api_path = ' + file['api_path'])
    print('File Path = ' + file['path'])
    webbrowser.open(file['path'], new=2)
    print('--------------------------------------------------------------------------------------------')
    for library in file['content']:
        print(library)
    print('')
