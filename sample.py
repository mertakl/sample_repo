
@staticmethod
def analyze_title(title: str | None) -> Tuple[str | None, List[LegalEntityPublicationType] | None]:
    if not title:
        return None, None
    
    # Define language keywords with their language codes
    language_keywords = {
        "fr": {
            "RUBRIQUE CONSTITUTION": LegalEntityPublicationType.Constitution,
            "RUBRIQUE FIN": LegalEntityPublicationType.Termination,
            "DENOMINATION": LegalEntityPublicationType.NameChange,
            "SIEGE SOCIAL": LegalEntityPublicationType.RegisteredOfficeChange,
            "ADRESSE AUTRE QUE LE SIEGE SOCIAL": LegalEntityPublicationType.OtherAddressChange,
            "OBJET": LegalEntityPublicationType.ObjectChange,
            "CAPITAL, ACTIONS": LegalEntityPublicationType.CapitalAndShares,
            "DEMISSIONS, NOMINATIONS": LegalEntityPublicationType.ResignationsAndAppointments,
            "ASSEMBLEE GENERALE": LegalEntityPublicationType.GeneralAssembly,
            "ANNEE COMPTABLE": LegalEntityPublicationType.FiscalYearChange,
            "STATUTS": LegalEntityPublicationType.StatutesChange,
            "MODIFICATION FORME JURIDIQUE": LegalEntityPublicationType.LegalFormChange,
            "RUBRIQUE RESTRUCTURATION": LegalEntityPublicationType.Restructuring,
            "COMPTES ANNUELS": LegalEntityPublicationType.AnnualAccounts,
            "RADIATION D'OFFICE": LegalEntityPublicationType.OfficialDeRegistration,
            "DIVERS": LegalEntityPublicationType.Other,
        },
        "nl": {
            "RUBRIEK OPRICHTING": LegalEntityPublicationType.Constitution,
            "RUBRIEK EINDE": LegalEntityPublicationType.Termination,
            "BENAMING": LegalEntityPublicationType.NameChange,
            "MAATSCHAPPELIJKE ZETEL": LegalEntityPublicationType.RegisteredOfficeChange,
            "ADRES ANDERE DAN DE MAATSCH. ZETEL": LegalEntityPublicationType.OtherAddressChange,
            "VOORWERP": LegalEntityPublicationType.ObjectChange,
            "DOEL": LegalEntityPublicationType.ObjectChange,
            "KAPITAAL, AANDELEN": LegalEntityPublicationType.CapitalAndShares,
            "KAPITAAL - AANDELEN": LegalEntityPublicationType.CapitalAndShares,
            "ONTSLAGEN - BENOEMINGEN": LegalEntityPublicationType.ResignationsAndAppointments,
            "ALGEMENE VERGADERING": LegalEntityPublicationType.GeneralAssembly,
            "BOEKJAAR": LegalEntityPublicationType.FiscalYearChange,
            "STATUTEN": LegalEntityPublicationType.StatutesChange,
            "WIJZIGING RECHTSVORM": LegalEntityPublicationType.LegalFormChange,
            "RUBRIEK HERSTRUCTURERING": LegalEntityPublicationType.Restructuring,
            "JAARREKENING": LegalEntityPublicationType.AnnualAccounts,
            "AMBTSHALVE DOORHALING": LegalEntityPublicationType.OfficialDeRegistration,
            "DIVERSEN": LegalEntityPublicationType.Other,
        },
        "de": {
            "RUBRIK GRUENDUNG": LegalEntityPublicationType.Constitution,
        }
    }
    
    found_types = set()
    first_language = None
    
    # Iterate through each language and its keywords
    for lang_code, keywords in language_keywords.items():
        for keyword, pub_type in keywords.items():
            if keyword in title:
                found_types.add(pub_type)
                if first_language is None:
                    first_language = lang_code
    
    if not found_types:
        return None, None
    
    # Guaranteed order for the tests
    return first_language, sorted(list(found_types), key=lambda t: t.name)
