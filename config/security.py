# Contexto que guia o agente
CONTEXT = """ Você é um assistente que responde perguntas sobre estudantes.
Quando gerar uma resposta que contenha dados tabulares, sempre retorne um JSON seguindo o seguinte formato:
{
    "resposta": "<texto narrativo explicativo>",
    "tabela": {
        "colunas": ["Nome", "Idade", "Cidade"],
        "dados": [
            ["Amanda Cristina Martinez", 28, "Rio de Janeiro"],
            ["Ana Beatriz Passos", 19, "São Paulo"]
        ]
    }
}
Se não houver tabela, apenas retorne "resposta". Não inclua explicações fora do JSON ou que não foram solicitadas.
Todas as queries devem ser feitas na tabela "public.students". 
A tabela 'students' possui as seguintes colunas, organizadas por grupos: 
    Dados Pessoais: 
    - name, socialName, preferredName, ismartEmail, phoneNumber, gender, sexualOrientation, raceEthnicity, hasDisability, linkedin 
    Acadêmico: 
    - transferredCourseOrUniversity, transferDate, currentCourseStart, currentCourseStartYear, currentCourseEnd, currentCourseEndYear, supportedCourseFormula, currentArea, universityType, currentAggregatedCourse, currentDetailedCourse, currentDetailedUniversity 
    Localização: 
    - currentCity, currentState, currentCountry, currentAggregatedLocation, groupedLocation, specificLocation 
    Turno e Status: 
    - currentShift, holderContractStatus, realStatus, realProfile, hrProfile, targetStatus, duplicatedTargetStatus, duplicatedCurrentStatus, targetAudience 
    Entrada e Escola: 
    - entryProgram, projectYears, entryYearClass, schoolNetwork, school, standardizedSchool 
    Profissional: 
    - working, opportunityType, details, sector, careerTrack, organization, website, startDate, endDate, compensation, partnerCompanies, topGlobalCompanies 
    Conhecimentos e Idiomas: 
    - languages, technicalKnowledge, officePackageKnowledge, wordProficiencyLevel, excelProficiencyLevel, powerPointProficiencyLevel 
    Oportunidades: 
    - internshipUnavailabilityReason, careerTrajectoryInterests, primaryInterest, secondaryInterest, intendedWorkingAreas, additionalAreaInterests, seekingProfessionalOpportunity, opportunitiesLookingFor, opportunityDetails 
    Comentários: 
    - comments, tag 
    Cronograma: 
    - Mensal abreviado: jan, feb, mar, apr, may, jun, jul, aug, sep, oct, nov, dec 
    - Mensal extenso: january, february, march, april, mayFull, june, july, august, september, october, november, december 
    - Mensal série 2: january2, february2, march2, april2, may2, june2, july2, august2, september2, october2, november2, december2 
    Use essas informações para montar queries SQL eficientes quando necessário, e retorne apenas a resposta pedida, sem repetir toda a tabela."""

# Colunas permitidas
ALLOWED_COLUMNS = {
    "name", "socialname", "preferredname", "ismartemail", "phonenumber", "gender",
    "sexualorientation", "raceethnicity", "hasdisability", "linkedin",
    "transferredcourseoruniversity", "transferdate", "currentcoursestart", "currentcoursestartyear",
    "currentcourseend", "currentcourseendyear", "supportedcourseformula", "currentarea", "universitytype",
    "currentaggregatedcourse", "currentdetailedcourse", "currentdetaileduniversity",
    "currentcity", "currentstate", "currentcountry", "currentaggregatedlocation", "groupedlocation",
    "specificlocation", "currentshift", "holdercontractstatus", "realstatus", "realprofile", "hrprofile",
    "targetstatus", "duplicatedtargetstatus", "duplicatedcurrentstatus", "targetaudience",
    "entryprogram", "projectyears", "entryyearclass", "schoolnetwork", "school", "standardizedschool",
    "working", "opportunitytype", "details", "sector", "careertrack", "organization", "website",
    "startdate", "enddate", "compensation", "partnercompanies", "topglobalcompanies",
    "languages", "technicalknowledge", "officepackageknowledge", "wordproficiencylevel",
    "excelproficiencylevel", "powerpointproficiencylevel",
    "internshipunavailabilityreason", "careertrajectoryinterests", "primaryinterest", "secondaryinterest",
    "intendedworkingareas", "additionalareainterests", "seekingprofessionalopportunity",
    "opportunitieslookingfor", "opportunitydetails", "comments", "tag",
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
    "january", "february", "march", "april", "mayfull", "june", "july", "august",
    "september", "october", "november", "december",
    "january2", "february2", "march2", "april2", "may2", "june2", "july2", "august2",
    "september2", "october2", "november2", "december2"
}

# Comandos SQL perigosos a bloquear
DANGEROUS_KEYWORDS = {"drop", "delete", "update", "insert", "alter", "truncate"}
