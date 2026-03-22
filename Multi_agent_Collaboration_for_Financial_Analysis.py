import warnings
warnings.filterwarnings('ignore')

import os
import json
import requests
from flask import Flask, request, jsonify, send_from_directory
from pydantic import BaseModel
from crewai import Agent, Task, Crew, Process
from crewai_tools import ScrapeWebsiteTool
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Retrieve API key from environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL_NAME = os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo")

# Ensure API key is set
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found in environment variables. Please set it in your .env file.")

app = Flask(__name__, static_folder='.', static_url_path='')

class YahooFinanceScrapeTool(ScrapeWebsiteTool):
    def scrape(self, url):
        if "yahoo.com" not in url:
            raise ValueError("This tool only supports scraping Yahoo Finance.")
        return super().scrape(url)

scrape_tool = YahooFinanceScrapeTool()

# Agents
data_analyst_agent = Agent(
    role="Data Analyst",
    goal="Monitor and analyze market data in real-time to identify trends and predict market movements.",
    backstory="Specializing in financial markets, this agent uses statistical modeling and machine learning to provide crucial insights.",
    verbose=True,
    allow_delegation=True,
    tools=[scrape_tool]
)

trading_strategy_agent = Agent(
    role="Trading Strategy Developer",
    goal="Develop and test various trading strategies based on insights from the Data Analyst Agent.",
    backstory="Equipped with a deep understanding of financial markets and quantitative analysis, this agent devises and refines trading strategies.",
    verbose=True,
    allow_delegation=True,
    tools=[scrape_tool]
)

execution_agent = Agent(
    role="Trade Advisor",
    goal="Suggest optimal trade execution strategies based on approved trading strategies.",
    backstory="This agent specializes in analyzing the timing, price, and logistical details of potential trades.",
    verbose=True,
    allow_delegation=True,
    tools=[scrape_tool]
)

risk_management_agent = Agent(
    role="Risk Advisor",
    goal="Evaluate and provide insights on the risks associated with potential trading activities.",
    backstory="Armed with a deep understanding of risk assessment models and market dynamics, this agent scrutinizes the potential risks of proposed trades.",
    verbose=True,
    allow_delegation=True,
    tools=[scrape_tool]
)

# Tasks

data_analysis_task = Task(
    description="""
        Continuously monitor and analyze market data for the selected stock ({stock_selection}).
        Use statistical modeling and machine learning to identify trends and predict market movements.
    """,
    expected_output="""
        Insights and alerts about significant market opportunities or threats for {stock_selection}.
    """,
    agent=data_analyst_agent
)

strategy_development_task = Task(
    description="""
        Develop and refine trading strategies based on the insights from the Data Analyst and
        user-defined risk tolerance ({risk_tolerance}). Consider trading preferences ({trading_strategy_preference}).
    """,
    expected_output="""
        A set of potential trading strategies for {stock_selection} that align with the user's risk tolerance.
    """,
    agent=trading_strategy_agent
)

execution_planning_task = Task(
    description="""
        Analyze approved trading strategies to determine the best execution methods for {stock_selection},
        considering current market conditions and optimal pricing.
    """,
    expected_output="""
        Detailed execution plans suggesting how and when to execute trades for {stock_selection}.
    """,
    agent=execution_agent
)

risk_assessment_task = Task(
    description="""
        Evaluate the risks associated with the proposed trading strategies and execution plans for {stock_selection}.
        Provide a detailed analysis of potential risks and suggest mitigation strategies.
    """,
    expected_output="""
        A comprehensive risk analysis report detailing potential risks and mitigation recommendations for {stock_selection}.
    """,
    agent=risk_management_agent
)

# Crew
financial_trading_crew = Crew(
    agents=[data_analyst_agent, trading_strategy_agent, execution_agent, risk_management_agent],
    tasks=[data_analysis_task, strategy_development_task, execution_planning_task, risk_assessment_task],
    manager_llm=ChatOpenAI(model="gpt-3.5-turbo", temperature=0.5),
    process=Process.hierarchical,
    verbose=True
)

def truncate_input(data, max_length=1000):
    """
    Truncate input data to ensure it does not exceed the model's context window.
    """
    if isinstance(data, str) and len(data) > max_length:
        return data[:max_length] + "..."  # Truncate and add ellipsis
    elif isinstance(data, dict):
        # Truncate each string field in the dictionary
        return {k: truncate_input(v, max_length) if isinstance(v, str) else v for k, v in data.items()}
    elif isinstance(data, list):
        # Truncate each item in the list
        return [truncate_input(item, max_length) for item in data]
    return data

def summarize_output(raw_output, max_length=500):
    """
    Summarize or truncate the raw output to ensure it is concise.
    """
    if len(raw_output) > max_length:
        return raw_output[:max_length] + "..."  # Truncate and add ellipsis
    return raw_output

def get_yahoo_finance_url(stock_symbol):
    return f"https://finance.yahoo.com/quote/{stock_symbol}"

# API endpoint for frontend to trigger analysis
@app.route('/analyze-trading', methods=['POST'])
def analyze_trading():
    data = request.json
    try:
        stock_symbol = data.get("stock_selection", "").upper()
        yahoo_url = get_yahoo_finance_url(stock_symbol)
        # Update task descriptions to explicitly use Yahoo Finance
        data_analysis_task.description = (
            f"Continuously monitor and analyze market data for {stock_symbol} using Yahoo Finance ({yahoo_url}). "
            "Use statistical modeling and machine learning to identify trends and predict market movements. "
            "Scrape only Yahoo Finance for all data."
        )
        strategy_development_task.description = (
            f"Develop and refine trading strategies for {stock_symbol} based on insights from Yahoo Finance ({yahoo_url}), "
            f"user-defined risk tolerance ({data.get('risk_tolerance', '')}), and trading preferences ({data.get('trading_strategy_preference', '')})."
        )
        execution_planning_task.description = (
            f"Analyze approved trading strategies for {stock_symbol} using Yahoo Finance ({yahoo_url}) to determine the best execution methods, "
            "considering current market conditions and optimal pricing."
        )
        risk_assessment_task.description = (
            f"Evaluate the risks associated with the proposed trading strategies and execution plans for {stock_symbol} using Yahoo Finance ({yahoo_url}). "
            "Provide a detailed analysis of potential risks and suggest mitigation strategies."
        )

        # Optionally, pass the Yahoo Finance URL in the input data for agent/tool use
        data["yahoo_finance_url"] = yahoo_url

        result = financial_trading_crew.kickoff(inputs=data)
        # Collect meaningful, non-placeholder outputs
        main_points = []
        if hasattr(result, 'tasks_output') and result.tasks_output:
            for task in result.tasks_output:
                if hasattr(task, 'raw') and task.raw:
                    raw = task.raw.strip()
                    if any([
                        raw.lower().startswith("i have delegated"),
                        raw.lower().startswith("due to the inability"),
                        raw.lower().startswith("i will now proceed"),
                        "coworker" in raw.lower(),
                        "alternative sources" in raw.lower(),
                        "unable to access" in raw.lower(),
                        "not available" in raw.lower(),
                        "no data" in raw.lower()
                    ]):
                        continue
                    main_points.append(raw)
        # Limit to 3 main points/paragraphs and join as markdown (no headings)
        if main_points:
            final_output = "\n\n".join(main_points[:3])
        else:
            final_output = "_No meaningful analysis could be generated for this stock at this time._"

        final_output = final_output.strip()

        return jsonify({
            "success": True,
            "result": {
                "final_output": final_output
            }
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# Serve frontend UI
@app.route('/')
def frontend():
    return send_from_directory('.', 'frontend.html')

if __name__ == '__main__':
    app.run(debug=True)
