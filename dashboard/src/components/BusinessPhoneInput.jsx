"use client";

import { useState } from "react";
import PhoneNumberInput, { getCountries, getCountryCallingCode } from "react-phone-number-input/input";
import countryNames from "react-phone-number-input/locale/en.json";
import { parsePhoneNumberFromString } from "libphonenumber-js/max";
import styles from "./BusinessPhoneInput.module.css";

const COUNTRIES = getCountries().sort((a, b) => countryNames[a].localeCompare(countryNames[b], "en"));

/**
 * Controlled optional phone number in E.164 format (empty string when cleared).
 * Country selection is local presentation state; extensions remain in the separate field.
 * Native select retains keyboard navigation and platform mobile pickers without flag requests.
 */
export default function BusinessPhoneInput({ value = "", onChange, onBlur, id = "contact-phone", disabled = false, ...inputProps }) {
    const [selection, setSelection] = useState(() => ({ country: parsePhoneNumberFromString(value)?.country || "US", value }));
    // Config loads/reset can replace the controlled value after mount. Derive its country
    // without an effect that would overwrite an explicit choice for shared calling codes.
    const country = value === selection.value ? selection.country : parsePhoneNumberFromString(value)?.country || selection.country;

    const changeNumber = (nextValue) => {
        const next = nextValue || "";
        const parsed = parsePhoneNumberFromString(next);
        const nextCountry = parsed?.country || country;
        setSelection({ country: nextCountry, value: next });
        onChange(next);
    };

    const changeCountry = (event) => {
        const nextCountry = event.target.value;
        // Keep the national digits, replace the prefix. Never reinterpret an old
        // international prefix as part of the new national number.
        const national = parsePhoneNumberFromString(value)?.nationalNumber || "";
        const next = national ? `+${getCountryCallingCode(nextCountry)}${national}` : "";
        setSelection({ country: nextCountry, value: next });
        onChange(next);
    };

    return (
        <div className={styles.control}>
            <select
                className={styles.country}
                aria-label="Phone country"
                value={country}
                disabled={disabled}
                onChange={changeCountry}
            >
                {COUNTRIES.map((code) => (
                    <option key={code} value={code}>
                        {countryNames[code]} (+{getCountryCallingCode(code)})
                    </option>
                ))}
            </select>
            <PhoneNumberInput
                {...inputProps}
                id={id}
                className={styles.number}
                defaultCountry={country}
                useNationalFormatForDefaultCountryValue={false}
                value={value || undefined}
                onChange={changeNumber}
                onBlur={onBlur}
                disabled={disabled}
                smartCaret={false}
            />
        </div>
    );
}
