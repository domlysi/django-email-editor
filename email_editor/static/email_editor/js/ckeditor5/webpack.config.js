'use strict';

const path = require('path');
const webpack = require('webpack');
const { bundler, styles } = require('@ckeditor/ckeditor5-dev-utils');
const { CKEditorTranslationsPlugin } = require('@ckeditor/ckeditor5-dev-translations');
const TerserWebpackPlugin = require('terser-webpack-plugin');

module.exports = {
    devtool: false,
    performance: { hints: false },

    entry: path.resolve(__dirname, 'src', 'ckeditor.js'),

    output: {
        library: 'ClassicEditor',
        path: path.resolve(__dirname, 'build'),
        filename: 'ckeditor.js',
        libraryTarget: 'umd',
        libraryExport: 'default',
    },

    optimization: {
        minimizer: [
            new TerserWebpackPlugin({
                terserOptions: {
                    output: {
                        comments: /^!/,
                    },
                },
                extractComments: false,
            }),
        ],
    },

    plugins: [
        new CKEditorTranslationsPlugin({
            language: 'en',
            additionalLanguages: 'all',
        }),
        new webpack.BannerPlugin({
            banner: bundler.getLicenseBanner(),
            raw: true,
        }),
    ],

    module: {
        rules: [
            {
                test: /\.svg$/,
                use: ['raw-loader'],
            },
            {
                test: /\.css$/,
                use: [
                    {
                        loader: 'style-loader',
                        options: {
                            injectType: 'singletonStyleTag',
                            attributes: {
                                'data-cke': true,
                            },
                        },
                    },
                    'css-loader',
                    {
                        loader: 'postcss-loader',
                        options: {
                            postcssOptions: styles.getPostCssConfig({
                                themeImporter: {
                                    themePath: require.resolve('@ckeditor/ckeditor5-theme-lark'),
                                },
                                minify: true,
                            }),
                        },
                    },
                ],
            },
        ],
    },

    resolve: {
        extensions: ['.js'],
    },
};
