import isEmail from "validator/lib/isEmail.js";
import { parsePhoneNumberFromString } from "libphonenumber-js/max";

export function splitContactPhone(value = "") {
    const match = /^(.*?)(?:\s*[xX#]\s*(\d+))?$/.exec(value.trim());
    return { number: match?.[1]?.trim() || "", extension: match?.[2] || "" };
}

export function normalizeContactPhone(number, extension = "") {
    if (!number.trim() && !extension) return "";
    if (number.length > 50 || !/^\+?[0-9 ().-]+$/.test(number.trim()) ||
        (extension && !/^\d{1,10}$/.test(extension))) return null;
    const phone = parsePhoneNumberFromString(number, { extract: false });
    if (!phone?.isValid()) return null;
    return phone.number + (extension ? ` x${extension}` : "");
}

export function validateContactFields(form) {
    const errors = {};
    const email = form.contact_email.trim();
    if (email.length > 254 || !isEmail(email, { allow_utf8_local_part: false })) {
        errors.contact_email = "Enter a valid email address, such as support@example.com.";
    }
    if (normalizeContactPhone(form.contact_phone, form.contact_phone_extension || "") === null) {
        errors.contact_phone = "Select a country and enter a valid phone number, or leave it empty.";
    }
    if (form.contact_phone_extension && !/^\d{1,10}$/.test(form.contact_phone_extension)) {
        errors.contact_phone_extension = "Use 1–10 digits for the extension.";
    }
    return errors;
}
