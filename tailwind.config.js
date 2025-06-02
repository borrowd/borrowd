/** @type {import('tailwindcss').Config} */
module.exports = {
    theme: {
        colors: {
            indigo: {
                300: "#d9e1f4",
                600: "#2c51a1",
            },
        },
        extend: {
            colors: {
                honey: {
                    300: "#fdf7e1",
                    600: "#b97c21",
                },
                plum: {
                    300: "#f0d7eb",
                    600: "#73325b",
                },
                fern: {
                    300: "#ebf7ed",
                    600: "#537533",
                },
            },
        },
    },
    safelist: [
        {
            pattern: /(bg|text|border)-(indigo|honey|plum|fern)-(300|600)/,
        },
    ]
}